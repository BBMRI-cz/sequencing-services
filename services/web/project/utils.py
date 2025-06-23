import os
import shutil


def threaded_copy(src, dest, pseudonym, pred_num, full_run, job_id):
    if full_run:
        shutil.copytree(src, dest, ignore=shutil.ignore_patterns('FASTQ'))

        # group all FASTQ files from Samples together into one FASTQ folder
        dest_fastq = os.path.join(dest, 'FASTQ')
        os.makedirs(dest_fastq, exist_ok=True)
        samples_path = os.path.join(src, 'Samples')

        for sample_dir in os.listdir(samples_path):
            fastq_dir = os.path.join(samples_path, sample_dir, 'FASTQ')
            if os.path.isdir(fastq_dir):
                for filename in os.listdir(fastq_dir):
                    src_file = os.path.join(fastq_dir, filename)
                    dest_file = os.path.join(dest_fastq, filename)
                    shutil.copy2(src_file, dest_file)
        _rename_whole_run(dest, pseudonym, pred_num)
    else:
        shutil.copytree(src, dest)
        _rename_files_recursively(pseudonym, pred_num, dest)


def _rename_whole_run(path, samples_pseudo, samples_pred):
    _replace_file_inside_multiple(os.path.join(path, "Alignment", "AdapterCounts.txt"), samples_pseudo, samples_pred)
    _replace_file_inside_multiple(os.path.join(path, "SampleSheet.csv"), samples_pseudo, samples_pred)
    for pseudo, pred in zip(samples_pseudo, samples_pred):
        _rename_files_recursively(pseudo, pred, os.path.join(path, "Samples"))
        _rename_files_recursively(pseudo, pred, os.path.join(path, "FASTQ"))


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
