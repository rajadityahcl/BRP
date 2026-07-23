-- =====================================================================
-- vw_submission_analytics
-- ---------------------------------------------------------------------
-- One wide, denormalised row per submission: fact_submission pre-joined
-- to all seven dimensions. This is what the underwriting assistant (and
-- Power BI) should query for portfolio analytics -- no JOINs required,
-- and every measure is already a proper numeric type.
--
-- Run this once in DBeaver against the brp_case_study database.
-- LEFT JOINs are used so a submission is never dropped just because a
-- dimension key is missing.
-- =====================================================================

CREATE OR REPLACE VIEW vw_submission_analytics AS
SELECT
    f.SubmissionId,
    f.CustomerId,
    a.AgentID,
    u.UnderwriterID,
    p.ProductCode,
    p.PolicyType,
    g.OperatingState,
    c.CurrentCarrier,
    i.NAICSCode,
    i.Industry,
    d.FullDate      AS SubmissionDate,
    d.Year          AS SubmissionYear,
    d.Quarter       AS SubmissionQuarter,
    d.Month         AS SubmissionMonth,
    d.MonthName     AS SubmissionMonthName,
    f.SubmissionType,
    f.Status,
    f.Bound,                      -- 1 = bound, 0 = not bound  -> bind rate = AVG(Bound)
    f.CurrentPremium,
    f.CurrentLimit,
    f.CurrentRetention,
    f.AnnualRevenue,
    f.CommissionRate,
    f.EmployeeCount,
    f.PriorClaimsCount,
    f.YearsInBusiness
FROM fact_submission f
LEFT JOIN dim_agent        a ON f.AgentKey       = a.AgentKey
LEFT JOIN dim_underwriter  u ON f.UnderwriterKey = u.UnderwriterKey
LEFT JOIN dim_product      p ON f.ProductKey     = p.ProductKey
LEFT JOIN dim_geography    g ON f.GeoKey         = g.GeoKey
LEFT JOIN dim_carrier      c ON f.CarrierKey     = c.CarrierKey
LEFT JOIN dim_industry     i ON f.IndustryKey    = i.IndustryKey
LEFT JOIN dim_date         d ON f.DateKey        = d.DateKey;

-- If your read-only user was granted SELECT on the whole schema
-- (GRANT SELECT ON brp_case_study.* ...), it can already read this view.
-- Otherwise grant it explicitly:
--   GRANT SELECT ON brp_case_study.vw_submission_analytics TO 'readonly_user'@'%';
--   FLUSH PRIVILEGES;

-- Quick sanity checks:
--   SELECT COUNT(*) FROM vw_submission_analytics;
--   SELECT AgentID, AVG(Bound) AS bind_rate, COUNT(*) AS submissions
--     FROM vw_submission_analytics GROUP BY AgentID ORDER BY bind_rate ASC LIMIT 10;
