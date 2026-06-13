select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
    



select skill
from "pipeline"."gold"."skills_frequency"
where skill is null



      
    ) dbt_internal_test