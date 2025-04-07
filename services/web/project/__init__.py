import re

from flask import Flask, jsonify, Response, send_from_directory, request, render_template, session
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import Enum
import enum
from werkzeug.utils import secure_filename
import os
import pandas as pd
import shutil
from threading import Thread
import sys

FINISHED = False

ALLOWED_EXTENSIONS = {'csv', 'xlsx'}

BBM_parts = {
    "": ["1", "2", "3", "4", "5", "53", "54", "55", "56"],
    "s": ["K", "L", "PD", "S", "SD", "T"],
    "b": ["7", "PR"],
    "d": ["gD", "PK"]
}

app = Flask(__name__)
app.config.from_object("project.config.Config")
db = SQLAlchemy(app)

app.secret_key = "Secret BBM sequecing key"


class PatientPseudo(db.Model):
    __tablename__ = "patient_pseudonymization"
    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.String(128))
    patient_pseudo_id = db.Column(db.String(128))

    def __init__(self, patient_id, patient_pseudo_id):
        self.patient_id = patient_id
        self.patient_pseudo_id = patient_pseudo_id

    @property
    def serialize(self):
        return {
            "ID": self.id,
            "patient_ID": self.patient_id,
            "patient_pseudo_ID": self.patient_pseudo_id
        }


class PredictivePseudo(db.Model):
    __tablename__ = "predictive_pseudonymization"
    id = db.Column(db.Integer, primary_key=True)
    predictive_id = db.Column(db.String(128))
    predictive_id_unified = db.Column(db.String(128))
    predictive_pseudo_id = db.Column(db.String(128))

    def __init__(self, predictive_id, predictive_id_unified, predictive_pseudo_id):
        self.predictive_id = predictive_id
        self.predictive_id_unified = predictive_id_unified
        self.predictive_pseudo_id = predictive_pseudo_id

    @property
    def serialize(self):
        return {
            "predictive_ID": self.predictive_id,
            "predictive_ID_unified": self.predictive_id_unified,
            "predictive_pseudo_ID": self.predictive_pseudo_id
        }


class SamplePseudo(db.Model):
    __tablename__ = "sample_pseudonymization"
    id = db.Column(db.Integer, primary_key=True)
    sample_id = db.Column(db.String(128))
    sample_pseudo_id = db.Column(db.String(128))

    def __init__(self, sample_id, sample_pseudo_id):
        self.sample_id = sample_id
        self.sample_pseudo_id = sample_pseudo_id

    @property
    def serialize(self):
        return {
            "id": self.id,
            "sample_ID": self.sample_id,
            "sample_pseudo_ID": self.sample_pseudo_id
        }


def modify_predictive_number(pred_number):

    # matching 2022-1234 ([whole_year]-[number])
    if re.match(r"^20[1-2][\d]-[\d]{1,4}", pred_number):
        year, id = pred_number.split("-", 1)
        return f"{id}-{year[2:]}"

    # matching 22-1234 ([year]-[number]) etc.
    if re.match(r"^[1-2][\d]\-[\d]{1,4}", pred_number):
        year, id = pred_number.split("-", 1)
        return f"{id}-{year}"

    # matching 1245-22 ([number]-[year]) etc.
    if re.match(r"^[\d]{1,4}\-[1-2][\d]", pred_number):
        return pred_number

    # matching 22_1234 ([year]_[number]) etc.
    if re.match(r"^[1-2][\d]_[\d]{1,4}", pred_number):
        year, id = pred_number.split("_", 1)
        return f"{id}-{year}"

    # matching 2022_1234 ([whole_year]_[number])
    if re.match(r"^20[1-2][\d]_[\d]{1,4}", pred_number):
        year, id = pred_number.split("_", 1)
        return f"{id}-{year[2:]}"

    return pred_number


def _add_sample_id_to_excel(df, type_of_df):
    sample_ids = []
    row_val = [column for column in df.columns if "prohláš" in column and "číslo" in column][0]

    for i, row in df.iterrows():
        material = row["materiál"].split("/")[0]
        biobank_part = [key for key, val in BBM_parts.items() if material in val]
        sample_id = f'BBM{biobank_part[0]}:20{str(row[row_val]).replace("/", ":")}:{material}'
        sample_ids.append(sample_id)

    df["sample_id"] = sample_ids

    return df


def _check_if_sample_has_sequencing(df, db):
    has_seq = [db.session.execute(db.Select(SamplePseudo).filter_by(sample_id=sample_id)).one_or_none() is not None for sample_id in df["sample_id"].tolist()]
    df["has sequencing"] = has_seq
    return df


def _look_if_pred_number_has_data(wanted_pred_number, db):
    pseudonym = db.session.execute(db.Select(PredictivePseudo).filter_by(predictive_id_unified=wanted_pred_number)).one_or_none()
    return pseudonym


def find_file(file_we_look_for, path, year):
    full_year = f"20{year}"
    full_year_path = os.path.join(path, full_year)
    if not os.path.exists(full_year_path):
        return None

    existing_sequence_types = [folder_sequence_type for folder_sequence_type in os.listdir(full_year_path)]

    for sequence_type in existing_sequence_types:
        match sequence_type:
            case "MiSEQ":
                run_type_dir = os.path.join(full_year_path, "MiSEQ", "complete-runs")
            case "NextSeq":
                run_type_dir = os.path.join(full_year_path, "NextSeq")
            case _:
                continue  # Skip any sequence_type that is not MiSEQ or NextSeq

        if os.path.exists(run_type_dir):
            for run in os.listdir(run_type_dir):
                sample_dir = os.path.join(run_type_dir, run, "Samples")
                if os.path.exists(sample_dir):
                    for sample in os.listdir(sample_dir):
                        if sample == file_we_look_for:
                            return os.path.join(sample_dir, sample)

    return None


def _replace_file_inside(file_name, text_to_replace, replaced_text):
    if not os.path.exists(file_name):
        return

    with open(file_name, "rb") as f:
        data = f.read()

    with open(file_name, "wb") as f:
        data = data.replace(str.encode(text_to_replace), str.encode(replaced_text))
        f.write(data)


def _replace_file_inside_multiple(file_name, texts_to_replace, replaced_texts):
    if not os.path.exists(file_name):
        return

    with open(file_name, "r") as f:
        data = f.read()

    for rep, new in zip(texts_to_replace, replaced_texts):
        data = data.replace(rep, new)

    with open(file_name, "w") as f:
        f.write(data)


def _rename_files_recursively(text_to_replace, replaced_text, current_file):
    """Recursively renames all files ina run that contain predictive number with
    pseudonymized predictive number. Does it in a way to not create conflicts in a renaming

    Parameters
    ----------
    text_to_replace : str
        Text that should be replaced in a file name
    replaced_text : str
        Text that will replace "text_to_replace" in a file name
    current_file : str
        Path of a current directory that will be renamed and then listed to rename inner file
    """
    current_file_renamed = current_file.replace(text_to_replace, replaced_text, 1)
    os.rename(current_file, current_file_renamed)
    for file in os.listdir(current_file_renamed):
        file_path = os.path.join(current_file_renamed, file)
        if os.path.isdir(file_path):
            _rename_files_recursively(text_to_replace, replaced_text, file_path)
        else:
            if "_StatInfo" in file:
                _replace_file_inside(os.path.join(current_file_renamed, file), text_to_replace, replaced_text)
            os.rename(os.path.join(current_file_renamed, file), os.path.join(current_file_renamed, file.replace(text_to_replace, replaced_text)))


def _rename_whole_run(path, samples_pseudo, samples_pred):
    _replace_file_inside_multiple(os.path.join(path, "Alignment", "AdapterCounts.txt"), samples_pseudo, samples_pred)
    _replace_file_inside_multiple(os.path.join(path, "SampleSheet.csv"), samples_pseudo, samples_pred)
    for pseudo, pred in zip(samples_pseudo, samples_pred):
        _rename_files_recursively(pseudo, pred, os.path.join(path, "Samples"))


def threaded_copy(src, dest, pseudonym, pred_num, full_run):
    global FINISHED
    shutil.copytree(src, dest)
    if full_run:
        _rename_whole_run(dest, pseudonym, pred_num)
    else:
        _rename_files_recursively(pseudonym, pred_num, dest)
    FINISHED = True


@app.route("/")
def main():
    return render_template("main.html")

#######################
# PATHOLOGY RETRIEVAL #
#######################


@app.route("/pathology-data-retrieval", methods=["GET", "POST"])
def retrieveSequences():
    if request.method == 'POST':
        pseudonym = _look_if_pred_number_has_data(request.form["pred_number"], db)
        if pseudonym is None:
            return render_template("index-no-pred-number.html", pred_num=request.form["pred_number"])
        else:
            year = request.form["pred_number"].split("-")[-1]
            path_to_file = find_file(pseudonym[0].predictive_pseudo_id, "/RUNS", year)
            session["file_path"] = path_to_file
            session["pseudonym"] = pseudonym[0].predictive_pseudo_id
            session["pred_number"] = pseudonym[0].predictive_id
            return render_template("index4.html", data={"pred_num": session["pred_number"], "pseudonym": pseudonym[0].predictive_pseudo_id, "path": path_to_file})
    else:
        return render_template("index3.html")


@app.route("/transfering_file_run", methods=["POST"])
def transfer_file_run():
    if request.method == 'POST':
        final_path = "/".join(session["file_path"].split("/")[:6])
        only_run = final_path.split("/")[-1]

        samples_pseudo = os.listdir(os.path.join(final_path, "Samples"))
        samples_pred = [db.session.execute(db.Select(PredictivePseudo).filter_by(predictive_pseudo_id=pseudo)).one_or_none() for pseudo in samples_pseudo]
        samples_pred = [pred[0].predictive_id for pred in samples_pred if pred is not None]

        if os.path.exists(f"/RETRIEVED/{only_run}"):
            return render_template("index-already-retrieved.html", path=f"/RETRIEVED/{only_run}")

        global FINISHED
        FINISHED = False
        thread = Thread(target=threaded_copy, args=(final_path, f"/RETRIEVED/{only_run}", samples_pseudo, samples_pred, True))
        thread.daemon = True
        thread.start()
        return render_template("index5.html", data={"path": f"/NO-BACKUP-SPACE/RETRIEVED/{only_run}", "coppied_full": False})
    return render_template("index5.html")


@app.route("/transfering_file_sample", methods=["POST"])
def transfer_file_sample():
    if request.method == 'POST':
        only_sample = session["file_path"].split("/")[-1]
        if os.path.exists(f"/RETRIEVED/{only_sample}"):
            return render_template("index-already-retrieved.html", path=f"/RETRIEVED/{only_sample}")

        if os.path.exists(f"/RETRIEVED/{session['pred_number']}"):
            return render_template("index-already-retrieved.html", path=f"/RETRIEVED/{session['pred_number']}")

        global FINISHED
        FINISHED = False
        thread = Thread(target=threaded_copy, args=(session["file_path"], f"/RETRIEVED/{only_sample}", session["pseudonym"], session["pred_number"], False))
        thread.daemon = True
        thread.start()
        return render_template("index5.html", data={"path": f"/NO-BACKUP-SPACE/RETRIEVED/{only_sample}", "coppied_full": False})
    return render_template("index5.html")


@app.route("/data_copied")
def data_copied():
    return render_template("index6.html")


@app.route("/copy_status")
def copy_status():
    return jsonify(dict(status=('finished' if FINISHED else 'running')))


#######################
# BBM Sequencing INFO #
#######################

@app.route("/bbm-sequencing-upload", methods=['GET', 'POST'])
def uploadFile():
    print("req type:", request.method)
    print(request.method == 'POST')
    if request.method == 'POST' and request.files["file"]:
        print("IN POST")
        file = request.files["file"]
        print(file)
        data_filemane = secure_filename(file.filename)
        print(data_filemane)
        file_path = os.path.join(app.config["UPLOAD_FOLDER"], data_filemane)
        print(file_path)
        file.save(file_path)
        print("File saved!")
        session["upload_data_file_path"] = file_path

        return render_template('index2.html')
    return render_template("index.html")


@app.route('/bbm-sequencing-download')
def downloadData():
    data_file_path = session.get('upload_data_file_path', None)
    if ".csv" in data_file_path:
        print("IN CSV")
        uploaded_df = pd.read_csv(data_file_path, sep=",")
        print(uploaded_df.columns)
        df = _add_sample_id_to_excel(uploaded_df, "csv")
        df = _check_if_sample_has_sequencing(df, db)
        download_file_name = "bbm_data_with_sequecing_info.csv"
        df_path = os.path.join(app.config["DOWNLOAD_FOLDER"], download_file_name)
        df.to_csv(df_path, sep=";", index=False)
    elif ".xlsx" in data_file_path:
        print("IN EXCEL")
        uploaded_df = pd.read_excel(data_file_path, sheet_name="List1", engine="openpyxl")
        print(uploaded_df.columns)
        df = _add_sample_id_to_excel(uploaded_df, "xlsx")
        df = _check_if_sample_has_sequencing(df, db)
        download_file_name = "bbm_data_with_sequecing_info.xlsx"
        df_path = os.path.join(app.config["DOWNLOAD_FOLDER"], download_file_name)
        df.to_excel(df_path, sheet_name="List1", index=False)
    else:
        uploaded_df = None
        return '''
                !DOCTYPE html>
                <html>
                <head>
                    <title>Uploading & Reading CSV file</title>
                </head>
                <body>
                <h1> WRONG FILE FORMAT only CSV or XLSX.</h1>
                </body>
                </html>
                '''

    return send_from_directory(app.config["DOWNLOAD_FOLDER"], download_file_name)

##########
# DB API #
##########


@app.route("/api/patient", methods=["POST"])
def post_new_patient():
    data = request.json
    print(data)
    if data:
        existing_data = PatientPseudo.query.filter_by(patient_id=data["patient_ID"]).first()
        if existing_data is None:
            db.session.add(PatientPseudo(patient_id=data["patient_ID"], patient_pseudo_id=data["patient_pseudo_ID"]))
            db.session.commit()
            return jsonify(isError=False, message="Success", statusCode=200, data=data), 200
        else:
            return jsonify(isError=True, message="Data already in database", statusCode=409, data=data), 409
    else:
        return jsonify(isError=True, message="Invalid input data", statusCode=404, data=data), 404


@app.route("/api/predictive", methods=["POST"])
def post_new_predictive():
    data = request.json
    print(data)
    if data:
        existing_data = PredictivePseudo.query.filter_by(predictive_id=data["predictive_ID"]).first()
        if existing_data is None:
            db.session.add(PredictivePseudo(predictive_id=data["predictive_ID"], predictive_id_unified=modify_predictive_number(data["predictive_ID"]), predictive_pseudo_id=data["predictive_pseudo_ID"]))
            db.session.commit()
            return jsonify(isError=False, message="Success", statusCode=200, data=data), 200
        else:
            return jsonify(isError=True, message="Data already in database", statusCode=409, data=data), 409
    else:
        return jsonify(isError=True, message="Invalid input data", statusCode=404, data=data), 404


@app.route("/api/sample", methods=["POST"])
def post_new_sample():
    data = request.json
    print(data)
    if data:
        existing_data = SamplePseudo.query.filter_by(sample_id=data["sample_ID"]).first()
        if existing_data is None:
            db.session.add(SamplePseudo(sample_id=data["sample_ID"], sample_pseudo_id=data["sample_pseudo_ID"]))
            db.session.commit()
            return jsonify(isError=False, message="Success", statusCode=200, data=data), 200
        else:
            return jsonify(isError=True, message="Data already in database", statusCode=409, data=data), 409
    else:
        return jsonify(isError=True, message="Invalid input data", statusCode=404, data=None), 404


@app.route("/api/patient/<wanted_patient_id>", methods=["GET"])
def get_patient_by_patient_id(wanted_patient_id):
    patient = PatientPseudo.query.filter_by(patient_id=wanted_patient_id).first()
    if patient:
        return jsonify(patient.serialize)
    else:
        return jsonify(isError=True, message="Patient not found", statusCode=404), 404


@app.route("/api/predictive/<wanted_predictive_id>", methods=["GET"])
def get_predictive_by_predictive_id(wanted_predictive_id):
    predictive = PredictivePseudo.query.filter_by(predictive_id=wanted_predictive_id).first()
    if predictive:
        return jsonify(predictive.serialize)
    else:
        return jsonify(isError=True, message="Predictive number not found", statusCode=404), 404


@app.route("/api/sample/<wanted_sample_id>", methods=["GET"])
def get_sample_by_sample_id(wanted_sample_id):
    sample = SamplePseudo.query.filter_by(sample_id=wanted_sample_id).first()
    if sample:
        return jsonify(sample.serialize)
    else:
        return jsonify(isError=True, message="Sample not found", statusCode=404), 404
