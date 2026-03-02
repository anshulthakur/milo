import os

def get_all_files(path):
    """Returns a list of all files in the path."""
    files_list = []
    if os.path.isfile(path):
        return [os.path.abspath(path)]
    
    for root, dirs, files in os.walk(path):
        if '.git' in dirs:
            dirs.remove('.git')
        for file in files:
            files_list.append(os.path.join(root, file))
    return files_list