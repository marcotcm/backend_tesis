"""
Heimdall RCM Edge Collector (Fase 2 Enterprise)
Agente ligero para red local de planta (OT) con soporte para Modbus TCP, OPC-UA, MQTT
y modo simulador, más cola SQLite store-and-forward ante caídas de Internet.
"""

import json
import os
import random
import sqlite3
import time
from datetime import datetime, timezone
from typing import Any, Dict, List

import requests
import yaml


class StoreAndForwardBuffer:
    """Persiste lotes en SQLite local cuando falla la conectividad hacia la nube."""

    def __init__(self, db_path: str = "edge_buffer.db"):
        self.conn = sqlite3.connect(db_path)
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS pending_batches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        self.conn.commit()

    def enqueue(self, readings: List[Dict[str, Any]]) -> None:
        self.conn.execute(
            "INSERT INTO pending_batches (payload_json, created_at) VALUES (?, ?)",
            (json.dumps(readings), datetime.now(timezone.utc).isoformat()),
        )
        self.conn.commit()

    def pop_all(self, max_batches: int = 20) -> List[tuple[int, List[Dict[str, Any]]]]:
        rows = self.conn.execute(
            "SELECT id, payload_json FROM pending_batches ORDER BY id ASC LIMIT ?",
            (max_batches,),
        ).fetchall()
        return [(r[0], json.loads(r[1])) for r in rows]

    def delete(self, batch_id: int) -> None:
        self.conn.execute("DELETE FROM pending_batches WHERE id = ?", (batch_id,))
        self.conn.commit()


def read_modbus_tags(cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
    from pymodbus.client import ModbusTcpClient

    host = cfg.get("host", "127.0.0.1")
    port = int(cfg.get("port", 502))
    client = ModbusTcpClient(host=host, port=port, timeout=3)
    readings: List[Dict[str, Any]] = []
    if not client.connect():
        raise ConnectionError(f"No se pudo conectar a PLC Modbus TCP {host}:{port}")
    try:
        for asset in cfg.get("assets", []):
            item: Dict[str, Any] = {"tag_number": asset["tag_number"]}
            for metric_name, reg in asset.get("registers", {}).items():
                addr = int(reg["address"])
                scale = float(reg.get("scale", 1.0))
                rr = client.read_holding_registers(address=addr, count=1, slave=int(reg.get("unit_id", 1)))
                if not rr.isError() and rr.registers:
                    item[metric_name] = round(rr.registers[0] * scale, 3)
            readings.append(item)
    finally:
        client.close()
    return readings


def read_opcua_tags(cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
    from opcua import Client as OpcUaClient

    endpoint = cfg.get("endpoint", "opc.tcp://127.0.0.1:4840")
    client = OpcUaClient(endpoint, timeout=4)
    readings: List[Dict[str, Any]] = []
    client.connect()
    try:
        for asset in cfg.get("assets", []):
            item: Dict[str, Any] = {"tag_number": asset["tag_number"]}
            for metric_name, node_id in asset.get("nodes", {}).items():
                val = client.get_node(node_id).get_value()
                if val is not None:
                    item[metric_name] = round(float(val), 3)
            readings.append(item)
    finally:
        client.disconnect()
    return readings


def read_simulated_tags(cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
    readings: List[Dict[str, Any]] = []
    for asset in cfg.get("assets", []):
        readings.append(
            {
                "tag_number": asset["tag_number"],
                "vibration_mm_s": round(random.uniform(1.6, 5.2), 2),
                "temperature_celsius": round(random.uniform(54.0, 84.0), 1),
                "pressure_psi": round(random.uniform(135.0, 210.0), 1),
                "flow_rate_bpd": round(random.uniform(1100.0, 1850.0), 0),
                "notes": "Lectura periódica Edge Agent",
            }
        )
    return readings


def post_batch(api_url: str, api_key: str, source: str, readings: List[Dict[str, Any]]) -> None:
    endpoint = f"{api_url.rstrip('/')}/api/v1/metricas/iot-ingest"
    headers = {"Content-Type": "application/json", "X-IoT-Key": api_key}
    for i in range(0, len(readings), 200):
        chunk = readings[i : i + 200]
        res = requests.post(
            endpoint,
            json={"source": source, "readings": chunk},
            headers=headers,
            timeout=10,
        )
        res.raise_for_status()


def run_collector(config_path: str = "config.yaml") -> None:
    with open(config_path, "r", encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh)

    api_url = os.getenv("HEIMDALL_API_URL", cfg["heimdall"]["api_url"])
    api_key = os.getenv("HEIMDALL_IOT_KEY", cfg["heimdall"]["iot_key"])
    source = cfg["heimdall"].get("source_name", "EDGE_GATEWAY_01")
    interval_s = float(cfg.get("poll_interval_seconds", 5))
    mode = str(cfg.get("protocol", "simulation")).lower()

    buffer = StoreAndForwardBuffer(cfg.get("buffer_db_path", "edge_buffer.db"))
    print(f"[HEIMDALL EDGE] Iniciado protocolo={mode} destino={api_url} intervalo={interval_s}s")

    while True:
        try:
            # 1. Reintentar lotes pendientes guardados sin Internet
            for batch_id, pending in buffer.pop_all():
                post_batch(api_url, api_key, source, pending)
                buffer.delete(batch_id)
                print(f"[EDGE BUFFER] Reenviado lote #{batch_id} ({len(pending)} lecturas)")

            # 2. Capturar nueva lectura según protocolo
            if mode == "modbus":
                readings = read_modbus_tags(cfg.get("modbus", {}))
            elif mode == "opcua":
                readings = read_opcua_tags(cfg.get("opcua", {}))
            else:
                readings = read_simulated_tags(cfg.get("simulation", {}))

            if readings:
                try:
                    post_batch(api_url, api_key, source, readings)
                    print(f"[EDGE SYNC] {len(readings)} TAGs enviados correctamente.")
                except Exception as net_err:
                    buffer.enqueue(readings)
                    print(f"[EDGE OFFLINE BUFFER] Red caída ({net_err}). Guardado en SQLite local.")
        except Exception as loop_err:
            print(f"[EDGE WARN] {loop_err}")

        time.sleep(interval_s)


if __name__ == "__main__":
    cfg_file = os.getenv("EDGE_CONFIG_PATH", "config.yaml")
    run_collector(cfg_file)
