select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
    



select canonical_role
from "pipeline"."gold"."salary_trends"
where canonical_role is null



      
    ) dbt_internal_test