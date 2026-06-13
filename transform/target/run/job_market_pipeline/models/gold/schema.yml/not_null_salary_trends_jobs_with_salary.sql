select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
    



select jobs_with_salary
from "pipeline"."gold"."salary_trends"
where jobs_with_salary is null



      
    ) dbt_internal_test