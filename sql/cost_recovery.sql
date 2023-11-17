-- Queries to manually run as part of the cost-recovery process
-- (recovering Azure spending from not-core-funded projects)


-- Export Query 1
-- Get all cost_recovery rows with the latest subscription names
select cr."id", finance_id, "month", finance_code, sd.display_name, cr.subscription_id, amount
from accounting.cost_recovery cr
join (
	select max("id") as max_id, subscription_id
	from accounting.subscription_details sd
	group by subscription_id
) latest_names
    on latest_names.subscription_id = cr.subscription_id
join accounting.subscription_details sd
    on sd.id = latest_names.max_id
where cr.month >= '2022-04-00'; -- the first day of the recovery period


-- Export Query 2
-- Get a breakdown of each subscription's usage
select
	u.subscription_id,
	display_name,
	--product,
	date_trunc('month', u."date") as the_date,
	sum(total_cost) as total_cost,
	sum(amortised_cost) as amortised_cost,
	sum(cost) as cost
from accounting.usage u
join (
	-- Limit to the latest subscription_detail ID for each subscription
	select max("id") as max_id, subscription_id
	from accounting.subscription_details sd
	group by subscription_id
) latest_names
    on latest_names.subscription_id = u.subscription_id
join accounting.subscription_details sd
    on sd.id = latest_names.max_id
where "date" >= '2022-10-00'  -- the recovery-period start date
and "date" < '2023-01-00'  -- one day after the recovery-period end date
and u.subscription_id in (
    select distinct subscription_id
    from accounting.cost_recovery
)
group by
	u.subscription_id,
	display_name,
	--product,
	date_trunc('month', u."date");


-- Export Query 3
-- Include the finance rows
select sd.display_name,
       f.id,
  	   f.subscription_id,
  	   f.finance_code,
  	   f.date_from,
  	   f.date_to,
  	   f.amount,
  	   f.ticket,
  	   f.priority
from accounting.finance f
join (
	select max("id") as max_id, subscription_id
	from accounting.subscription_details sd
	group by subscription_id
) latest_names
    on latest_names.subscription_id = f.subscription_id
join accounting.subscription_details sd
    on sd.id = latest_names.max_id
where f.date_to >= '2022-10-00'  -- the recovery-period start date
and f.date_from < '2023-01-00';  -- one day after the recovery-period end date


-- Data Integrity Query 1
-- Date-from and date-to mismatches between approval and finance tables
-- We expect some mismatches but it is easy to be off by a month or a year
WITH fin_tbl AS (
    SELECT subscription_id, ticket, amount, date_from, date_to
    FROM accounting.finance
),
app_tbl AS (
    SELECT subscription_id, ticket, amount, date_from, date_to
    FROM accounting.approvals
),
names as (
	select
	    latest_names.subscription_id,
	    sd.display_name
	from (
	    select max("id") as max_id, subscription_id
		from accounting.subscription_details sd
		group by subscription_id
	) latest_names
	join accounting.subscription_details sd
	    on sd.id = latest_names.max_id
)
select
    n.display_name,
    app_tbl.subscription_id,
    app_tbl.ticket,
    app_tbl.date_from as "app_date_from",
    fin_tbl.date_from as "fin_date_from",
    fin_tbl.date_from - app_tbl.date_from as "startdiff",
    app_tbl.date_to as "app_date_to",
    fin_tbl.date_to as "fin_date_to",
    fin_tbl.date_to - app_tbl.date_to as "enddiff"
FROM fin_tbl
JOIN app_tbl
    ON fin_tbl.subscription_id = app_tbl.subscription_id
    AND fin_tbl.ticket = app_tbl.ticket
join names n
    on n.subscription_id = fin_tbl.subscription_id
where app_tbl.date_to > '2023-04-00'  -- First day of the financial year
-- and app_tbl.date_from > '2023-07-00' -- you may wish to limit to the recovery period
order by n.display_name asc;


-- Data Integrity Query 2
-- Approvals without a matching finance row
WITH names as (
	select
	    latest_names.subscription_id,
	    sd.display_name
	from (
	    select max("id") as max_id, subscription_id
		from accounting.subscription_details sd
		group by subscription_id
	) latest_names
	join accounting.subscription_details sd
	    on sd.id = latest_names.max_id
)
select n.display_name, a.*
from accounting.approvals a
join names n
  on n.subscription_id = a.subscription_id
where not exists (
  select 1
  from accounting.finance f
  where f.ticket like (a.ticket || '%')
)
and a.date_to > '2023-04-00' -- First day of the financial year
-- and a.date_from > '2023-07-00' -- you may wish to limit to the recovery period
order by n.display_name asc;


-- Data Integrity Query 3
-- Finance without a matching approvals row
select *
from accounting.finance f
where f.ticket not in (
  select distinct a.ticket
  from accounting.approvals a
)
and f.date_to >= '2023-07-01' -- first day of the recovery period
order by f.date_to asc;


-- Data Integrity Query 4
-- !!Note this should be run after the cost_recovery table has been updated!!
-- Costly subscriptions without cost recovery
-- These could simply be core-funded but worth checking those over ~£500
select sum(u.total_cost), u.subscription_name, date_trunc('month', u.date) themonth
from accounting."usage" u
where (u.subscription_id, date_trunc('month', u.date)) in (
  select * from (
    select distinct ub.subscription_id subid, date_trunc('month', ub.date) themonth
    from accounting.usage ub
    where date_trunc('month', ub.date) >= '2023-04-00'  -- the recovery-period start date
    and date_trunc('month', ub.date) < '2023-07-00'  -- one day after the recovery-period end date
  ) a
  where (a.subid, a.themonth) not in (
    select cr.subscription_id, cr."month"
    from accounting.cost_recovery cr
    where cr."month" >= '2023-04-00'  -- the recovery-period start date
    and cr."month" < '2023-07-00'  -- one day after the recovery-period end date
  )
)
and date_trunc('month', u.date) >= '2023-04-00'  -- the recovery-period start date
and date_trunc('month', u.date) < '2023-07-00'  -- one day after the recovery-period end date
group by u.subscription_name, date_trunc('month', u.date)
order by sum(u.total_cost) desc, date_trunc('month', u.date) asc;
