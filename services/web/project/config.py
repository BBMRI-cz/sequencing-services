import os


basedir = os.path.abspath(os.path.dirname(__file__))
# root_path = "/home/ubuntu/seq-services/services"


class Config(object):
    DOWNLOAD_FOLDER = "/home/app/web/downloads/"
    UPLOAD_FOLDER = "/home/app/web/uploads"
    SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL", "postgresql://")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
