
    
    

select
    url as unique_field,
    count(*) as n_records

from "pipeline"."silver"."jobs"
where url is not null
group by url
having count(*) > 1


