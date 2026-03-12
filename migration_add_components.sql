-- Migration: Add 'components' JSONB column to template tables
-- Run this in the Supabase Dashboard SQL Editor:
-- https://supabase.com/dashboard/project/fepljzntmbtcucbymtgq/sql/new

-- 1. Add components column to user_templates
ALTER TABLE public.user_templates
ADD COLUMN IF NOT EXISTS components JSONB DEFAULT '{}'::jsonb;

-- 2. Add components column to preset_templates
ALTER TABLE public.preset_templates
ADD COLUMN IF NOT EXISTS components JSONB DEFAULT '{}'::jsonb;

-- Verify columns were added
SELECT
  table_name,
  column_name,
  data_type
FROM information_schema.columns
WHERE table_name IN ('user_templates', 'preset_templates')
  AND column_name = 'components';
