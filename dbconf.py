import os
from dotenv import load_dotenv
import mysql.connector.pooling

load_dotenv()  

config={
    "user":os.getenv("DB_USER"),
    "password":os.getenv("DB_PASSWORD"),
    "host":os.getenv("DB_HOST"),
    "database":os.getenv("DB_NAME"),
    # "port": int(os.getenv("DB_PORT", 3306)),
    }

cnxpool=mysql.connector.pooling.MySQLConnectionPool(
    pool_name="mypool", 
    pool_size=20,
    pool_reset_session=True,  # 建議加入pool_reset_session=True,**config這一行 
    **config)


