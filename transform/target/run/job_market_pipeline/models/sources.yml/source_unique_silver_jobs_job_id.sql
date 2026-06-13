select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
    

select
    job_id as unique_field,
    count(*) as n_records

from "pipeline"."silver"."jobs"
where job_id is not null
group by job_id
having count(*) > 1



      
    ) dbt_internal_test