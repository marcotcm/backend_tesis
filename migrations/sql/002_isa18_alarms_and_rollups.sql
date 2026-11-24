-- =============================================================================
-- Heimdall RCM - Fase 2 Enterprise: Alarmas Industriales ISA-18.2 y Rollups Time-Series
-- Script idempotente seguro para ejecutar en Supabase SQL Editor / PostgreSQL.
-- No altera ni elimina registros existentes.
-- =============================================================================

CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- 1. Consola y Máquina de Estados de Alarmas Industriales ISA-18.2
CREATE TABLE IF NOT EXISTS public.industrial_alarms (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    equipment_id UUID NOT NULL REFERENCES public.equipments(id) ON DELETE CASCADE,
    metric_key VARCHAR(80) NOT NULL,
    state VARCHAR(24) NOT NULL DEFAULT 'ACTIVE_UNACK',
    priority VARCHAR(16) NOT NULL DEFAULT 'P2_HIGH',
    message TEXT NOT NULL,
    trigger_value NUMERIC(12, 3),
    threshold_value NUMERIC(12, 3),
    occurrence_count INTEGER NOT NULL DEFAULT 1,
    acknowledged_by UUID REFERENCES public.users(id) ON DELETE SET NULL,
    acknowledged_at TIMESTAMPTZ,
    ack_notes TEXT,
    shelved_until TIMESTAMPTZ,
    triggered_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    cleared_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 2. Historiador Time-Series pre-agregado por hora para gráficas de 24h / 7d / 30d
CREATE TABLE IF NOT EXISTS public.equipment_metrics_hourly (
    equipment_id UUID NOT NULL REFERENCES public.equipments(id) ON DELETE CASCADE,
    bucket_hour TIMESTAMPTZ NOT NULL,
    sample_count INTEGER NOT NULL DEFAULT 0,
    avg_vibration NUMERIC(10, 3),
    max_vibration NUMERIC(10, 3),
    avg_temperature NUMERIC(10, 3),
    max_temperature NUMERIC(10, 3),
    avg_pressure NUMERIC(10, 3),
    max_pressure NUMERIC(10, 3),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (equipment_id, bucket_hour)
);

-- 3. Índices de alto rendimiento para consultas SCADA e históricas
CREATE INDEX IF NOT EXISTS idx_metrics_history_eq_ts
    ON public.equipment_metrics_history (equipment_id, recorded_at DESC);

CREATE INDEX IF NOT EXISTS idx_industrial_alarms_state
    ON public.industrial_alarms (state, priority, triggered_at DESC);

CREATE INDEX IF NOT EXISTS idx_industrial_alarms_eq_metric
    ON public.industrial_alarms (equipment_id, metric_key, state);

CREATE INDEX IF NOT EXISTS idx_metrics_hourly_bucket
    ON public.equipment_metrics_hourly (equipment_id, bucket_hour DESC);
