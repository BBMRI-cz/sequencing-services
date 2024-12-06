from flask.cli import FlaskGroup
import xml.etree.ElementTree as ET
import os
from project import app, db, PatientPseudo, PredictivePseudo, SamplePseudo
import json
import re


cli = FlaskGroup(app)


@cli.command("create_db")
def create_db():
    db.drop_all()
    db.create_all()
    db.session.commit()


def _load_data_from_file(file_name, list_name):
    with open(file_name) as f:
        data_list = json.load(f)[list_name]

    return data_list


def _modify_predictive_number(pred_number):

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


@cli.command("fill_db")
def fill_db():

    patients = _load_data_from_file("/pseudo_tables/patients.json", "patients")
    predictives = _load_data_from_file("/pseudo_tables/predictive.json", "predictive")
    samples = _load_data_from_file("/pseudo_tables/samples.json", "samples")

    for patient in patients:
        db.session.add(PatientPseudo(patient["patient_ID"], patient["patient_pseudo_ID"]))

    for predictive in predictives:
        db.session.add(PredictivePseudo(predictive["predictive_number"], _modify_predictive_number(predictive["predictive_number"]), predictive["pseudo_number"]))

    for sample in samples:
        db.session.add(SamplePseudo(sample["sample_ID"], sample["pseudo_sample_ID"]))

    db.session.commit()


if __name__ == "__main__":
    cli()
