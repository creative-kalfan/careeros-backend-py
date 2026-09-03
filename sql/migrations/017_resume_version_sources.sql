-- ============================================================================
-- 017: Extend Resume Versions Source Check Constraint
--
-- Extends the CHECK constraint on public.resume_versions.source to allow
-- all first-class version provenance values:
--   - 'manual'               (default / manual edits / backfilled master)
--   - 'upload_parse'         (initial version created from file upload parsing)
--   - 'reparse'              (version created when re-parsing an existing resume)
--   - 'import'               (imported from external source)
--   - 'job_specific'         (derived version tailored for a specific job posting)
--   - 'suggestion'           (derived version created when accepting optimization suggestions)
--   - 'approved_improvement' (derived version created when applying approved ATS proposals)
--   - 'optimization'         (optimization-derived version)
--   - 'duplicate'            (duplicated version)
--
-- Preserves all existing historical values and rows.
-- ============================================================================

BEGIN;

-- Drop existing check constraint if present
ALTER TABLE public.resume_versions
    DROP CONSTRAINT IF EXISTS resume_versions_source_check;

-- Re-create check constraint with complete set of canonical provenance values
ALTER TABLE public.resume_versions
    ADD CONSTRAINT resume_versions_source_check
    CHECK (source IN (
        'manual',
        'upload_parse',
        'reparse',
        'import',
        'job_specific',
        'suggestion',
        'approved_improvement',
        'optimization',
        'duplicate'
    ));

COMMENT ON CONSTRAINT resume_versions_source_check ON public.resume_versions IS
    'Allowed resume version provenance sources: manual, upload_parse, reparse, import, job_specific, suggestion, approved_improvement, optimization, duplicate';

COMMIT;
