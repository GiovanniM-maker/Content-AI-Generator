-- Migration: Add design_spec JSONB column to user_templates and preset_templates
-- This column stores the structured DesignSystemSpec JSON that replaces
-- the old html_content-based template system.
--
-- The html_content column is NOT removed — it is kept for backward compatibility
-- and will be used as a cache for the rendered HTML from the design_spec.

-- 1. Add design_spec to user_templates
ALTER TABLE public.user_templates
    ADD COLUMN IF NOT EXISTS design_spec JSONB DEFAULT NULL;

-- 2. Add design_spec to preset_templates
ALTER TABLE public.preset_templates
    ADD COLUMN IF NOT EXISTS design_spec JSONB DEFAULT NULL;

-- 3. Verify columns exist
SELECT column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_name IN ('user_templates', 'preset_templates')
  AND column_name = 'design_spec';
