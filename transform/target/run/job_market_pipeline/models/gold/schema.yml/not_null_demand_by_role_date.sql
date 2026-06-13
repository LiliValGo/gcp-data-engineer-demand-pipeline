select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
    



select date
from "pipeline"."gold"."demand_by_role"
where date is null



      
    ) dbt_internal_test