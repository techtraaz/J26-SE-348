import sys

from app.graph import neo4j_client
from app.graph.migrate import all_statements, migrate

if __name__ == "__main__":
    if "--dry-run" in sys.argv:
        for stmt in all_statements():
            print(stmt + ";")
        sys.exit(0)
    try:
        done = migrate(neo4j_client.run_write)
        print(f"Applied {len(done)} statements")
        for row in neo4j_client.run_read(
            "SHOW INDEXES YIELD name, type, state WHERE type <> 'LOOKUP' "
            "RETURN name, type, state ORDER BY type, name"
        ):
            print(f"  {row['type']:<8} {row['state']:<8} {row['name']}")
    finally:
        neo4j_client.close_driver()
