select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
    



select pct_of_role_jobs
from "pipeline"."gold"."skills_frequency"
where pct_of_role_jobs is null



      
    ) dbt_internal_test