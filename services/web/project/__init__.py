import re
import uuid
from typing import Dict, List, Any

from flask import jsonify, Response, send_from_directory, request, render_template, session
from werkzeug.utils import secure_filename
import os
import pandas as pd
from .app import db, app
from .tasks import copy_multiple_samples_task, copy_multiple_runs_task
from .redis_client import redis_client
from .utils import threaded_copy

ALLOWED_EXTENSIONS = {'csv', 'xlsx'}

BBM_parts = {
    "": ["1", "2", "3", "4", "5", "53", "54", "55", "56"],
    "s": ["K", "L", "PD", "S", "SD", "T"],
    "b": ["7", "PR"],
    "d": ["gD", "PK"]
}


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
        return f"{year}_{id}"

    # matching 22-1234 ([year]-[number]) etc.
    if re.match(r"^[1-2][\d]\-[\d]{1,4}", pred_number):
        year, id = pred_number.split("-", 1)
        return f"20{year}_{id}"

    # matching 1245-22 ([number]-[year]) etc.
    if re.match(r"^[\d]{1,4}\-[1-2][\d]", pred_number):
        id, year = pred_number.split("-", 1)
        return f"20{year}_{id}"

    # matching 22_1234 ([year]_[number]) etc.
    if re.match(r"^[1-2][\d]_[\d]{1,4}", pred_number):
        year, id = pred_number.split("_", 1)
        return f"20{year}_{id}"

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


def _check_if_sample_has_sequencing(df):
    has_seq = [db.session.execute(db.Select(SamplePseudo).filter_by(sample_id=sample_id)).one_or_none() is not None for sample_id in df["sample_id"].tolist()]
    df["has sequencing"] = has_seq
    return df


def _look_if_pred_number_has_data(wanted_pred_number_base: str) -> List[PredictivePseudo]:
    target_ids = [
        wanted_pred_number_base,
        f"{wanted_pred_number_base}_RNA",
        f"{wanted_pred_number_base}_DNA"
    ]
    pseudonyms = (
        db.session
        .execute(
            db.select(PredictivePseudo).filter(
                PredictivePseudo.predictive_id_unified.in_(target_ids)
            )
        )
        .scalars()
        .all()
    )
    return pseudonyms


def find_file(file_we_look_for, path):
    year_pattern = re.compile(r'^(19|20)\d{2}$')
    year_dirs = [
        name for name in os.listdir(path)
        if os.path.isdir(os.path.join(path, name)) and year_pattern.match(name)
    ]
    for year_dir in year_dirs:
        full_year_path = os.path.join(path, year_dir)

        existing_sequence_types = [folder_sequence_type for folder_sequence_type in os.listdir(full_year_path)]

        directories_with_runs = []

        for sequence_type in existing_sequence_types:
            match sequence_type:
                case "MiSEQ":
                    subdirs = ["complete-runs", "mamma-print", "missing-analysis"]
                    for subdir in subdirs:
                        miseq_path = os.path.join(full_year_path, "MiSEQ", subdir)
                        if os.path.exists(miseq_path):
                            directories_with_runs.append(miseq_path)
                case "NextSeq":
                    nextseq_path = os.path.join(full_year_path, "NextSeq")
                    if os.path.exists(nextseq_path):
                        directories_with_runs.append(nextseq_path)
                case _:
                    continue  # Skip any sequence_type that is not MiSEQ or NextSeq

        for directory_with_runs in directories_with_runs:
            for run in os.listdir(directory_with_runs):
                sample_dir = os.path.join(directory_with_runs, run, "Samples")
                if os.path.exists(sample_dir):
                    for sample in os.listdir(sample_dir):
                        if sample == file_we_look_for:
                            return os.path.join(sample_dir, sample)

    return None


@app.route("/")
def main():
    return render_template("main.html")

#######################
# PATHOLOGY RETRIEVAL #
#######################


@app.route("/pathology-data-retrieval", methods=["GET", "POST"])
def retrieveSequences():
    if request.method == 'POST':
        base_pred_num = request.form["pred_number"]
        pseudonyms = _look_if_pred_number_has_data(base_pred_num)
        if not pseudonyms:
            return render_template("index-no-pred-number.html", pred_num=request.form["pred_number"])

        files = []
        for pseudo in pseudonyms:
            path_to_file = find_file(pseudo.predictive_pseudo_id, "/RUNS")
            files.append({
                "pseudonym": pseudo.predictive_pseudo_id,
                "pred_number": pseudo.predictive_id_unified,
                "path": path_to_file
            })

        session["files"] = files
        session["base_pred_num"] = base_pred_num

        return render_template("pathology_download.html",
                               base_pred_num=base_pred_num,
                               files=files)
    else:
        return render_template("pathology_search.html")


@app.route("/transfering_file_run", methods=["POST"])
def transfer_file_run():
    files = session.get("files", [])
    runs_data: Dict[str, Dict[str, Any]] = {}
    for f in files:
        parts = f["path"].strip("/").split("/")
        if "Samples" in parts:
            idx = parts.index("Samples")
            run_path = "/" + "/".join(parts[:idx])  # Path up to the run
            only_run = parts[idx - 1]
            runs_data[only_run] = {"run_path": run_path}

    missing_runs = {only_run: data for only_run, data in runs_data.items() if not os.path.exists(f"/RETRIEVED/{only_run}")}

    if not missing_runs:
        return jsonify({
            "status": "already_exists",
            "paths": [f"/NO-BACKUP-SPACE/RETRIEVED/{only_run}" for only_run in runs_data.keys()]
        })

    for only_run, data in missing_runs.items():
        run_path = data["run_path"]
        samples_pseudo = os.listdir(os.path.join(run_path, "Samples"))
        samples_pred_raw = [
            db.session.execute(db.Select(PredictivePseudo).filter_by(predictive_pseudo_id=pseudo)).one_or_none()
            for pseudo in samples_pseudo
        ]
        samples_pred = [pred[0].predictive_id for pred in samples_pred_raw if pred is not None]

        data["samples_pseudo"] = samples_pseudo
        data["samples_pred"] = samples_pred

    job_id = str(uuid.uuid4())

    copy_multiple_runs_task.delay(missing_runs, job_id)

    return jsonify({
        "status": "started",
        "job_id": job_id,
        "paths": [f"/NO-BACKUP-SPACE/RETRIEVED/{only_run}" for only_run in missing_runs.keys()]
    })


@app.route("/transfering_file_sample", methods=["POST"])
def transfer_file_sample():
    files = session.get("files", [])
    missing_samples = [file for file in files if not os.path.exists(f"/RETRIEVED/{file['pred_number']}")]

    if not missing_samples:
        return jsonify({
            "status": "already_exists",
            "paths": [f"/NO-BACKUP-SPACE/RETRIEVED/{file['pseudonym']}" for file in files]
        })

    job_id = str(uuid.uuid4())

    copy_multiple_samples_task.delay(missing_samples, job_id)

    return jsonify({
        "status": "started",
        "job_id": job_id,
        "paths": [f"/NO-BACKUP-SPACE/RETRIEVED/{f['pseudonym']}" for f in missing_samples]
    })


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

        return render_template('bbm_sequencing_success.html')
    return render_template("bbm_sequencing_upload.html")


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
            db.session.add(SamplePseudo(sample_id=data["sample_ID"], sample_pseudo_id=data["pseudo_sample_ID"]))
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


@app.route('/job-status/<job_id>')
def job_status(job_id):

    def event_stream():
        pubsub = redis_client.pubsub()
        pubsub.subscribe(job_id)
        for message in pubsub.listen():
            if message['type'] == 'message':
                yield f"data: {message['data']}\n\n"
    return Response(event_stream(), mimetype='text/event-stream')
