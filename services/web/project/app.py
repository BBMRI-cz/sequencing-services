import os

from flask import Flask
from flask_sqlalchemy import SQLAlchemy

app = Flask(__name__)
app.config.from_object("project.config.Config")

for _folder in (app.config["UPLOAD_FOLDER"], app.config["DOWNLOAD_FOLDER"]):
    os.makedirs(_folder, exist_ok=True)

db = SQLAlchemy(app)

app.secret_key = "Secret BBM sequecing key"
