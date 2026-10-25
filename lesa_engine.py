import hashlib
import json
import os
import re
import sqlite3
from datetime import datetime, timezone

class LesaEngine:
    """
    LESA (Light Without Data) Core Engine
    Phase 2 Complete: Offline Vault, Multi-Schema, SHA-256 Security, Mesh Relay, & Maintenance
    """

    TRANSLATIONS = {
        "en": {
            "title": "  LESA (Light Without Data) - Main Menu           ",
            "menu_1": "1. Fill & Save New Form (Offline)",
            "menu_2": "2. Vault Dashboard & Record Inspector",
            "menu_3": "3. Export Outbox to .lto Files (Bluetooth/USB)",
            "menu_4": "4. Ingest External .lto Files (Mesh Relay Mode)",
            "menu_5": "5. Simulate Network Sync (Upload Pending & Relay)",
            "menu_6": "6. Maintenance: Clear Synced Records",
            "menu_7": "7. Exit",
            "prompt_select": "Select an option (1-7): ",
            "prompt_form_type": "Select Form Template:\n  [1] NSFAS Bursary\n  [2] SASSA Grant\n  [3] Municipal Indigent Relief\nChoice (1-3): ",
            "prompt_name": "Enter Full Name: ",
            "prompt_id": "Enter SA ID Number (13 digits): ",
            "prompt_income": "Enter Household Monthly Income (e.g., R 12 000): ",
            "err_id": "Invalid SA ID: Must be exactly 13 numerical digits.",
            "err_income": "Invalid Income: Could not parse numerical value.",
            "status_saved": "SUCCESS_SAVED_LOCALLY",
            "export_success": "Successfully exported {count} pending form(s) as standalone .lto files!",
            "export_folder": "📁 Files saved in folder: '{folder}/' on device storage.",
            "export_empty": "No pending records to export.",
            "ingest_success": "Successfully ingested and verified {count} peer .lto package(s) into Relay Staging!",
            "ingest_empty": "No external .lto files found in the export folder to ingest.",
            "sync_start": "--- [LESA Mesh Relay & Sync Engine: Simulating Network Recovery] ---",
            "sync_none": "No pending or relayed forms found to sync.",
            "sync_tx": "📡 Transmitting Record #{id} [{form}] for {name}...",
            "sync_ok": "✅ Record #{id} verified & synced successfully!",
            "sync_tampered": "❌ Record #{id} INTEGRITY FAILED! Hash mismatch detected.",
            "cleanup_success": "Successfully purged {count} synced record(s) from local vault storage.",
            "cleanup_empty": "No synced records found to purge.",
            "exit": "Exiting LESA. Stay offline-ready!"
        }
    }

    def __init__(self, db_name="lesa_vault.db"):
        self.rules = {
            "sa_id_number": r"^\d{13}$",
            "monthly_income": r"^\d+(\.\d{1,2})?$"
        }
        self.db_name = db_name
        self.init_local_database()

    def get_text(self, key: str, **kwargs) -> str:
        dictionary = self.TRANSLATIONS["en"]
        text = dictionary.get(key, key)
        if kwargs:
            return text.format(**kwargs)
        return text

    def init_local_database(self):
        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS local_outbox (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT,
                form_type TEXT,
                applicant_name TEXT,
                payload_json TEXT,
                payload_hash TEXT,
                sync_status TEXT
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS relay_staging (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                received_timestamp TEXT,
                form_type TEXT,
                applicant_name TEXT,
                payload_json TEXT,
                payload_hash TEXT,
                relay_status TEXT
            )
        ''')

        conn.commit()
        conn.close()

    def clean_numerical_input(self, raw_val: str) -> str:
        return re.sub(r"[^\d.]", "", raw_val)

    def generate_payload_hash(self, payload_dict: dict) -> str:
        serialized = json.dumps(payload_dict, sort_keys=True)
        return hashlib.sha256(serialized.encode('utf-8')).hexdigest()

    def validate_and_save_payload(self, form_type: str, applicant_data: dict) -> dict:
        errors = []
        cleaned_data = {}

        raw_id = str(applicant_data.get("sa_id_number", ""))
        cleaned_id = re.sub(r"\D", "", raw_id)
        if re.match(self.rules["sa_id_number"], cleaned_id):
            cleaned_data["sa_id_number"] = cleaned_id
        else:
            errors.append(self.get_text("err_id"))

        raw_income = str(applicant_data.get("monthly_income", ""))
        cleaned_income = self.clean_numerical_input(raw_income)
        if re.match(self.rules["monthly_income"], cleaned_income):
            cleaned_income_val = float(cleaned_income)
            cleaned_data["monthly_income"] = cleaned_income_val
            
            if form_type == "NSFAS":
                cleaned_data["eligible"] = cleaned_income_val <= 29166.00
            elif form_type == "SASSA":
                cleaned_data["eligible"] = cleaned_income_val <= 7000.00   
            elif form_type == "MUNICIPAL":
                cleaned_data["eligible"] = cleaned_income_val <= 4500.00   
        else:
            errors.append(self.get_text("err_income"))

        cleaned_data["full_name"] = applicant_data.get("full_name", "").strip().title()
        cleaned_data["form_template"] = form_type

        if errors:
            return {"status": "VALIDATION_FAILED", "errors": errors}

        payload_hash = self.generate_payload_hash(cleaned_data)
        timestamp_str = datetime.now(timezone.utc).isoformat()
        
        lto_package = {
            "protocol": f"LESA-v0.1-{form_type}-ZERO-DATA",
            "timestamp": timestamp_str,
            "payload_hash": payload_hash,
            "payload": cleaned_data,
            "status": "READY_FOR_OPPORTUNISTIC_SYNC"
        }

        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO local_outbox (timestamp, form_type, applicant_name, payload_json, payload_hash, sync_status) VALUES (?, ?, ?, ?, ?, ?)",
            (timestamp_str, form_type, cleaned_data["full_name"], json.dumps(lto_package), payload_hash, "PENDING_SYNC")
        )
        conn.commit()
        conn.close()
        
        return {
            "status": self.get_text("status_saved"),
            "lto_package": lto_package
        }

    def export_outbox_to_lto_files(self):
        export_dir = "lesa_exports"
        os.makedirs(export_dir, exist_ok=True)
        
        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()
        cursor.execute("SELECT id, form_type, applicant_name, payload_json FROM local_outbox WHERE sync_status = 'PENDING_SYNC'")
        pending_items = cursor.fetchall()

        if not pending_items:
            conn.close()
            return 0, export_dir

        exported_count = 0
        for record_id, form_type, name, payload_str in pending_items:
            form_str = form_type if form_type else "nsfas"
            safe_name = "".join(c for c in name if c.isalnum() or c in (' ', '_')).strip().replace(" ", "_")
            filename = f"lesa_{form_str.lower()}_{record_id}_{safe_name}.lto"
            filepath = os.path.join(export_dir, filename)
            
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(payload_str)
            
            exported_count += 1

        conn.close()
        return exported_count, export_dir

    def ingest_external_lto_files(self):
        export_dir = "lesa_exports"
        if not os.path.exists(export_dir):
            return 0

        ingested_count = 0
        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()

        for filename in os.listdir(export_dir):
            if filename.endswith(".lto"):
                filepath = os.path.join(export_dir, filename)
                try:
                    with open(filepath, "r", encoding="utf-8") as f:
                        pkg = json.load(f)
                    
                    payload = pkg.get("payload", {})
                    stored_hash = pkg.get("payload_hash", "")
                    form_type = payload.get("form_template", "NSFAS")
                    name = payload.get("full_name", "Unknown Peer")
                    
                    recomputed = self.generate_payload_hash(payload)
                    if not stored_hash or stored_hash == "" or recomputed == stored_hash:
                        timestamp_str = datetime.now(timezone.utc).isoformat()
                        cursor.execute(
                            "INSERT INTO relay_staging (received_timestamp, form_type, applicant_name, payload_json, payload_hash, relay_status) VALUES (?, ?, ?, ?, ?, ?)",
                            (timestamp_str, form_type, name, json.dumps(pkg), stored_hash, "PENDING_RELAY_SYNC")
                        )
                        conn.commit()
                        ingested_count += 1
                except Exception as e:
                    print(f"Skipping malformed file {filename}: {e}")

        conn.close()
        return ingested_count

    def simulate_opportunistic_sync(self):
        print(f"\n{self.get_text('sync_start')}")
        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()
        
        cursor.execute("SELECT id, form_type, applicant_name, payload_json, payload_hash FROM local_outbox WHERE sync_status = 'PENDING_SYNC'")
        pending_local = cursor.fetchall()

        for record_id, form_type, name, payload_str, stored_hash in pending_local:
            form_str = form_type or "NSFAS"
            print(self.get_text('sync_tx', id=record_id, form=form_str, name=name))
            pkg = json.loads(payload_str)
            
            recomputed = self.generate_payload_hash(pkg["payload"])
            if not stored_hash or stored_hash == "" or recomputed == stored_hash:
                cursor.execute("UPDATE local_outbox SET sync_status = 'SYNCED' WHERE id = ?", (record_id,))
                conn.commit()
                print(self.get_text('sync_ok', id=record_id))
            else:
                print(self.get_text('sync_tampered', id=record_id))

        cursor.execute("SELECT id, form_type, applicant_name, payload_json, payload_hash FROM relay_staging WHERE relay_status = 'PENDING_RELAY_SYNC'")
        pending_relay = cursor.fetchall()

        for record_id, form_type, name, payload_str, stored_hash in pending_relay:
            form_str = form_type or "NSFAS"
            print(f"📡 [MESH RELAY] Transmitting Peer Record #{record_id} [{form_str}] for {name}...")
            pkg = json.loads(payload_str)
            recomputed = self.generate_payload_hash(pkg["payload"])
            if not stored_hash or stored_hash == "" or recomputed == stored_hash:
                cursor.execute("UPDATE relay_staging SET relay_status = 'RELAY_SYNCED' WHERE id = ?", (record_id,))
                conn.commit()
                print(f"✅ [MESH RELAY] Peer Record #{record_id} successfully bulk-synced!")
            else:
                print(f"❌ [MESH RELAY] Peer Record #{record_id} INTEGRITY FAILED!")

        if not pending_local and not pending_relay:
            print(self.get_text('sync_none'))

        conn.close()

    def get_vault_summary(self):
        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()
        cursor.execute("SELECT id, timestamp, form_type, applicant_name, payload_hash, sync_status FROM local_outbox")
        local_rows = cursor.fetchall()
        
        cursor.execute("SELECT id, received_timestamp, form_type, applicant_name, payload_hash, relay_status FROM relay_staging")
        relay_rows = cursor.fetchall()
        conn.close()
        return local_rows, relay_rows

    def get_record_detail(self, record_id: int):
        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()
        cursor.execute("SELECT payload_json FROM local_outbox WHERE id = ?", (record_id,))
        row = cursor.fetchone()
        conn.close()
        if row:
            return json.loads(row[0])
        return None

    def purge_synced_records(self):
        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM local_outbox WHERE sync_status = 'SYNCED'")
        deleted_count = cursor.rowcount
        conn.commit()
        conn.close()
        return deleted_count


if __name__ == "__main__":
    engine = LesaEngine()

    while True:
        print("\n==================================================")
        print(engine.get_text("title"))
        print("==================================================")
        print(engine.get_text("menu_1"))
        print(engine.get_text("menu_2"))
        print(engine.get_text("menu_3"))
        print(engine.get_text("menu_4"))
        print(engine.get_text("menu_5"))
        print(engine.get_text("menu_6"))
        print(engine.get_text("menu_7"))
        
        choice = input(f"\n{engine.get_text('prompt_select')}").strip()

        if choice == "1":
            print("\n--- Form Template Selector ---")
            form_choice = input(engine.get_text("prompt_form_type")).strip()
            form_map = {"1": "NSFAS", "2": "SASSA", "3": "MUNICIPAL"}
            selected_form = form_map.get(form_choice, "NSFAS")

            full_name = input(engine.get_text("prompt_name"))
            sa_id = input(engine.get_text("prompt_id"))
            income = input(engine.get_text("prompt_income"))

            user_data = {
                "full_name": full_name,
                "sa_id_number": sa_id,
                "monthly_income": income
            }

            result = engine.validate_and_save_payload(selected_form, user_data)
            print("\n" + json.dumps(result, indent=2, ensure_ascii=False))

        elif choice == "2":
            print("\n📦 LESA VAULT DASHBOARD & INSPECTOR:")
            local_outbox, relay_staging = engine.get_vault_summary()
            
            print("\n--- LOCAL OUTBOX ---")
            if not local_outbox:
                print("Local Vault is empty.")
            for item in local_outbox:
                form_label = item[2] or "NSFAS"
                short_hash = (item[4][:10] + "...") if item[4] else "N/A"
                print(f"[{item[0]}] Template: {form_label} | Name: {item[3]} | Hash: {short_hash} | Status: {item[5]}")

            print("\n--- MESH RELAY STAGING (Peer Files) ---")
            if not relay_staging:
                print("Relay staging is empty.")
            for item in relay_staging:
                form_label = item[2] or "NSFAS"
                short_hash = (item[4][:10] + "...") if item[4] else "N/A"
                print(f"[Peer #{item[0]}] Template: {form_label} | Name: {item[3]} | Hash: {short_hash} | Status: {item[5]}")

            inspect_id = input("\nEnter Local Record ID to inspect full payload (or press Enter to return): ").strip()
            if inspect_id.isdigit():
                detail = engine.get_record_detail(int(inspect_id))
                if detail:
                    print("\n--- RECORD PAYLOAD INSPECTION ---")
                    print(json.dumps(detail, indent=2, ensure_ascii=False))
                else:
                    print("Record ID not found.")

        elif choice == "3":
            print("\n--- [LESA Export Protocol] ---")
            count, folder = engine.export_outbox_to_lto_files()
            if count > 0:
                print(engine.get_text("export_success", count=count))
                print(engine.get_text("export_folder", folder=folder))
            else:
                print(engine.get_text("export_empty"))

        elif choice == "4":
            print("\n--- [LESA Mesh Relay Ingestion] ---")
            count = engine.ingest_external_lto_files()
            if count > 0:
                print(engine.get_text("ingest_success", count=count))
            else:
                print(engine.get_text("ingest_empty"))

        elif choice == "5":
            engine.simulate_opportunistic_sync()

        elif choice == "6":
            print("\n--- [LESA Storage Maintenance] ---")
            purged = engine.purge_synced_records()
            if purged > 0:
                print(engine.get_text("cleanup_success", count=purged))
            else:
                print(engine.get_text("cleanup_empty"))

        elif choice == "7":
            print(engine.get_text("exit"))
            break
        else:
            print("Invalid choice. Please enter a number between 1 and 7.")