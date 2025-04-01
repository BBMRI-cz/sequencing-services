from flask.cli import FlaskGroup
import xml.etree.ElementTree as ET
import os
from project import app, db, PatientPseudo, PredictivePseudo, SamplePseudo, modify_predictive_number
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




@cli.command("fill_db")
def fill_db():

    patients = _load_data_from_file("/pseudo_tables/patients.json", "patients")
    predictives = _load_data_from_file("/pseudo_tables/predictive.json", "predictive")
    samples = _load_data_from_file("/pseudo_tables/samples.json", "samples")

    for patient in patients:
        db.session.add(PatientPseudo(patient["patient_ID"], patient["patient_pseudo_ID"]))

    for predictive in predictives:
        db.session.add(PredictivePseudo(predictive["predictive_number"], modify_predictive_number(predictive["predictive_number"]), predictive["pseudo_number"]))

    for sample in samples:
        db.session.add(SamplePseudo(sample["sample_ID"], sample["pseudo_sample_ID"]))

    db.session.commit()


if __name__ == "__main__":
    cli()
