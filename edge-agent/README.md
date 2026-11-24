# Heimdall RCM — Agente Edge Local (OPC-UA / Modbus TCP / Store-and-Forward)

Servicio ligero desplegable en cualquier PC industrial, Raspberry Pi o servidor local dentro de la planta.

## Inicio rápido con Docker

```bash
cp config.example.yaml config.yaml
# Edita config.yaml con tus TAGs reales y la clave IOT_INGEST_API_KEY
docker build -t heimdall-edge-agent .
docker run -d --name heimdall-edge --restart unless-stopped \
  -v $(pwd)/config.yaml:/app/config.yaml \
  -v heimdall_edge_data:/data \
  heimdall-edge-agent
```

Si la conexión a Internet de la planta se cae, los paquetes se encolan en `/data/edge_buffer.db` (SQLite) y se reenvían automáticamente en orden al restablecerse la red.
