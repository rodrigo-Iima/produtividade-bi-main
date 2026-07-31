DO $grant_views$
DECLARE
    item record;
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_roles
        WHERE rolname = 'produtividade_reader'
    ) THEN
        RAISE EXCEPTION 'Role produtividade_reader does not exist';
    END IF;

    FOR item IN
        SELECT schemaname, viewname
        FROM pg_views
        WHERE schemaname = 'public'
    LOOP
        EXECUTE format(
            'GRANT SELECT ON %I.%I TO produtividade_reader',
            item.schemaname,
            item.viewname
        );
    END LOOP;
END
$grant_views$;
