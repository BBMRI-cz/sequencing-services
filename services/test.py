from pathlib import Path
import os

year=23
path = f"/muni-ss/MiSEQ/OrganisedRuns/20{year}/MiSEQ/" # 02340 # 210121_M02340_0246...

def find_file(start_dir, file_we_look_for):
    for folder_run_types in os.scandir(start_dir):
        for run in os.scandir(os.path.join(start_dir, folder_run_types.name)):
            for sample in os.scandir(os.path.join(start_dir, folder_run_types.name, run.name, "Samples")):
                if sample.name == file_we_look_for:
                    return sample.path
    return None

def find_file_old(name, path, year):
    for root, dirs, files in os.walk(f"{path}/20{year}/MiSEQ/"):
        # print(files)
        if name in dirs:
            return os.path.join(root, name)
    return None

print(find_file(path, "mmci_predictive_f4bfe619-7d59-4372-a2f9-df159e4d56"))

#print(find_file_old("mmci_predictive_f4bfe619-7d59-4372-a2f9-df159e4d5667", "/muni-ss/MiSEQ/OrganisedRuns/", "23"))
