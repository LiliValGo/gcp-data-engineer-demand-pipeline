select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
    



select mention_count
from "pipeline"."gold"."skills_frequency"
where mention_count is null



      
    ) dbt_internal_test