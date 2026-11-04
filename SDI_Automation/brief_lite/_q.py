"""Quick look into a Brief Lite database: python _q.py projects.db "SELECT ..." """
import sqlite3, sys
con = sqlite3.connect(sys.argv[1])
for r in con.execute(sys.argv[2]):
    print(r)
