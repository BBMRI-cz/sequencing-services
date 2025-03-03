# Seuquencing services
Tools and services for MMCI sequencing pipeline

- URL:  sequencing.int.mou.cz

## BBM Sequencing info
- Allows Biobanker to find if a set of samples does also have sequencing data
- Biobanker uploades a CSV or Excel file with specified format, the service adds new column with information of sequencing data are present for a given column

## Pathology data retrieval
- Allows pathologists to get back their uploded data from SensitiveCloud. 
- They can use predictive number to find a relevant sequencing run and then copy the run into `seq` server `/seq/NO_BACKUP_SPACE/RETRIEVED`

## Running the service
1. Go to `seq` server into `/services`
2. Run docker compose
```commandline
docker-compose -f compose.prod.yml up -d
```
3. Initialize database
```commandline
docker-compose exec web python manage.py create_db
```
4. Populate database with existing data
```commandline
docker-compose exec web python manage.py fill_db
```
5. (Optional) Verify if the data were sucesfully uploaded into the database
```commandline
docker-compose exec db psql --username=<prod_username> --dbname=<prod_db_name>
```

TEST
