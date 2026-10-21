from neo4j.exceptions import DriverError, Neo4jError

from app.graph import neo4j_client

if __name__ == "__main__":
    try:
        neo4j_client.get_driver().verify_connectivity()
        print("Connected:", neo4j_client.run_read("RETURN 1 AS ok"))
    except (DriverError, Neo4jError, ValueError) as exc:
        print("Neo4j connection failed:", exc)
    finally:
        neo4j_client.close_driver()
