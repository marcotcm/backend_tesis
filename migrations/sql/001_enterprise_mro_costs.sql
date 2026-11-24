-- =============================================================================
-- Heimdall RCM - Fase 1 Enterprise: Almacén MRO (Repuestos) y Costos de OT
-- Script idempotente seguro para ejecutar en Supabase SQL Editor / PostgreSQL.
-- No altera ni elimina registros existentes.
-- =============================================================================

CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- 1. Catálogo e Inventario de Repuestos MRO
CREATE TABLE IF NOT EXISTS public.spare_parts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    sku VARCHAR(80) UNIQUE NOT NULL,
    name VARCHAR(200) NOT NULL,
    description TEXT,
    category VARCHAR(80) NOT NULL DEFAULT 'General',
    unit_of_measure VARCHAR(30) NOT NULL DEFAULT 'unidad',
    stock_qty NUMERIC(12, 2) NOT NULL DEFAULT 0 CHECK (stock_qty >= 0),
    min_stock_qty NUMERIC(12, 2) NOT NULL DEFAULT 0 CHECK (min_stock_qty >= 0),
    unit_cost NUMERIC(12, 2) NOT NULL DEFAULT 0 CHECK (unit_cost >= 0),
    warehouse_location VARCHAR(120),
    supplier VARCHAR(160),
    taxonomy_id UUID REFERENCES public.equipment_taxonomy(id) ON DELETE SET NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_by UUID REFERENCES public.users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 2. Consumo de Repuestos por Orden de Trabajo (con snapshot histórico de costo)
CREATE TABLE IF NOT EXISTS public.work_order_parts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    work_order_id UUID NOT NULL REFERENCES public.work_orders(id) ON DELETE CASCADE,
    spare_part_id UUID NOT NULL REFERENCES public.spare_parts(id) ON DELETE RESTRICT,
    quantity_used NUMERIC(12, 2) NOT NULL CHECK (quantity_used > 0),
    unit_cost_snapshot NUMERIC(12, 2) NOT NULL DEFAULT 0,
    total_cost NUMERIC(12, 2) NOT NULL DEFAULT 0,
    notes TEXT,
    recorded_by UUID REFERENCES public.users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 3. Extensión aditiva de costos operacionales y tiempo de paro en Órdenes de Trabajo
ALTER TABLE public.work_orders
    ADD COLUMN IF NOT EXISTS labor_hours NUMERIC(10, 2) DEFAULT 0,
    ADD COLUMN IF NOT EXISTS labor_cost NUMERIC(12, 2) DEFAULT 0,
    ADD COLUMN IF NOT EXISTS parts_cost NUMERIC(12, 2) DEFAULT 0,
    ADD COLUMN IF NOT EXISTS downtime_hours NUMERIC(10, 2) DEFAULT 0,
    ADD COLUMN IF NOT EXISTS estimated_downtime_cost NUMERIC(12, 2) DEFAULT 0;

-- 4. Índices de consulta rápida
CREATE INDEX IF NOT EXISTS idx_spare_parts_sku ON public.spare_parts (sku);
CREATE INDEX IF NOT EXISTS idx_spare_parts_taxonomy ON public.spare_parts (taxonomy_id);
CREATE INDEX IF NOT EXISTS idx_spare_parts_active ON public.spare_parts (is_active);
CREATE INDEX IF NOT EXISTS idx_work_order_parts_wo ON public.work_order_parts (work_order_id);
CREATE INDEX IF NOT EXISTS idx_work_order_parts_part ON public.work_order_parts (spare_part_id);
