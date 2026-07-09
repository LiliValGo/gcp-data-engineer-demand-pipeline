import sys
import duckdb

def main():
    db_path = "data/pipeline.duckdb"
    print(f"Connected to {db_path} in read-only mode.")
    print("Type your SQL queries or write 'exit' or 'quit' to leave.\n")
    
    try:
        conn = duckdb.connect(db_path, read_only=True)
    except Exception as e:
        print(f"Error connecting to the database: {e}")
        sys.exit(1)
        
    while True:
        try:
            query = input("sql> ").strip()
            if not query:
                continue
            if query.lower() in ("exit", "quit", ".exit", ".quit"):
                break
            
            # Remove trailing semicolon if present for compatibility with conn.sql().show()
            if query.endswith(";"):
                query = query[:-1]
                
            conn.sql(query).show()
            print()
        except KeyboardInterrupt:
            print()
            break
        except Exception as e:
            print(f"Error: {e}\n")

if __name__ == "__main__":
    main()
