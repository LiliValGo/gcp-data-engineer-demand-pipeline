select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
    



select job_count
from "pipeline"."gold"."demand_by_role"
where job_count is null



      
    ) dbt_internal_test