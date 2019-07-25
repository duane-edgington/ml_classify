import os
import utils
import argparser
import train
from train import Train
from argparser import ArgParser
import tempfile
import glob
import random
import shutil
import tarfile
import wandb
import matplotlib
import numpy as np


def subsample(subset_percentage, train_dir):
    file_list = []
    print(f'Looking for prediction images in {train_dir}')
    file_glob = os.path.join(train_dir, '**/*.jpg')
    file_list.extend(glob.iglob(file_glob, recursive=True))

    if subset_percentage < 100:
        print(f'Randomly selecting {subset_percentage} % of images')
        k = len(file_list) * subset_percentage // 100
        indicies = random.sample(range(len(file_list)), k)
        file_list = [file_list[i] for i in indicies]

    # get labels names inferred from directory names and create subdirectory for each
    # TODO: verify whether this needs to be sorted or not
    all_dirs = [x[0] for x in os.walk(train_dir)]
    labels = [os.path.basename(x) for x in all_dirs[1:len(all_dirs)]]
    temp_dir = tempfile.mkdtemp()
    for l in labels:
        os.makedirs(os.path.join(temp_dir, l))
    print(f'Copying results to {temp_dir}')

    for src in file_list:
        fname = os.path.basename(src)
        class_name = os.path.basename(os.path.normpath(os.path.dirname(src)))
        dst = f'{temp_dir}/{class_name}/{fname}'
        shutil.copy(src, dst)

    import uuid
    out_tar = str(uuid.uuid4()) + '.tar.gz'
    print(f'Compressing results to {out_tar}')
    with tarfile.open(out_tar, "w:gz") as tar:
        tar.add(temp_dir, arcname='.')

    # clean-up
    shutil.rmtree(temp_dir)

    return out_tar, len(file_list)


def sliced_data(subset_percentage, project_home):
    classes = [folder for folder in os.listdir(os.path.join(project_home, 'data', 'train'))]
    for folder in classes:
        os.mkdir(os.path.join(project_home, 'data', 'temp', folder))
        image_number = (subset_percentage/100)*len(os.listdir(os.path.join(project_home, 'data', 'train', folder)))
        images = [image for image in os.listdir(os.path.join(project_home, 'data', 'train', folder))]
        uniques = set()
        for i in range(int(image_number)):
            index = np.random.randint(0, len(images))
            while index in uniques:
                index = np.random.randint()
            dst = os.path.join(project_home, 'data', 'temp', folder)
            src = os.path.join(project_home, 'data', 'train', folder, images[index])
            shutil.copy(src, dst)
    with tarfile.open(os.path.join(project_home, 'data', str(subset_percentage)+'_train.tar.gz'), 'w:gz') as tar:
        tar.add(os.path.join(project_home, 'data', 'temp'), arcname=os.path.basename(os.path.join(project_home, 'data', 'temp')))
    tar.close()


if __name__ == '__main__':

    # train the algorithm on incrementally increasing amounts of training data
    percent = [1, 2]
    training_size = {}
    hist_dict = {}

    parser = ArgParser()
    args = parser.parse_args()

    # check connection to wandb and log basic parameters before starting
    env = os.environ.copy()
    if 'WANDB_RUN_GROUP' not in env:
        print('Need to set WANDB_RUN_GROUP environment variable for this run')
        exit(-1)
    print('Connecting to wandb with group {}'.format(env['WANDB_RUN_GROUP']))
    wandb.init(project=args.project, job_type='training', name='kerasclassification-' + args.project,
               dir=os.getcwd())

    parser.log_params(wandb)

    # unpack original images
    project_home = os.environ.get('PROJECT_HOME')
    if not os.path.exists(os.path.join(project_home, 'data')):
        os.mkdir(os.path.join(project_home, 'data'))

    utils.unpack(project_home, args.train_tar, learning_curve=True)
    utils.unpack(project_home, args.val_tar, learning_curve=True)

    train_dir = os.path.join(project_home, 'data', 'train')
    val_dir = os.path.join(project_home, 'data', 'val')

    for p in percent:
        # subsample
        temp_dir = os.path.join(project_home, 'data', 'temp')
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)
        if not os.path.exists(temp_dir):
            os.mkdir(temp_dir)

        sliced_data(p, project_home)
        # subset_train_tar = temp_dir
        size = p

        # # replace training with subset
        args.train_tar = os.path.join(project_home, 'data', 'temp.tar.gz')
        print(args.train_tar)
        # train and store history of results
        model = Train().train_model(args)
        print(dir(model))
        hist_dict[p] = model
        training_size[p] = size

    # plot the last error of each training cycle and log as object in wandb
    # this will convert to plotly by default in wandb
    print(hist_dict)
    for percent, history in hist_dict.items():
        print(dir(history))
        train_error = 1 - history.history['acc'][-1]
        val_error = 1 - history.history['val_acc'][-1]
        matplotlib.plot(training_size[percent], train_error, 'ro')
        matplotlib.plot(training_size[percent], val_error,'bo')
    matplotlib.title('Learning curve')
    matplotlib.xlabel('Training set size')
    matplotlib.ylabel('Error')
    matplotlib.legend()
    wandb.log({"learning curve": matplotlib})
