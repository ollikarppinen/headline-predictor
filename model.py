#encoding: utf-8

import pandas
import numpy
import sys
import os
import keras
from keras import backend as K
from keras.models import Sequential
from keras.layers import Dense, LSTM, Dropout, Bidirectional, Activation
from keras.layers.convolutional import Convolution1D
from keras.layers.convolutional import MaxPooling1D
from keras.layers.embeddings import Embedding
from keras.preprocessing import sequence
from keras.utils.data_utils import get_file
from keras.callbacks import EarlyStopping, TensorBoard, ModelCheckpoint, ReduceLROnPlateau
from keras.optimizers import RMSprop
from sklearn.metrics import confusion_matrix
from datetime import datetime
from math import floor
import util
import json

########################### HYPERPARAMETERS ##############################

settings = {
    'ratio': 0.2,
    'title_max_len': 128,
    'batch_size': 64,
    'epochs': 10,
    'char_count_threshold': 100,
    'lstm': 64,
    'description': 'lstm 64 dropout 0.2',
    'dropout': 0.2
}

ts = datetime.now()
date_string = '-'.join(list(map(str, [ts.year, ts.month, ts.day, ts.hour, ts.minute])))
file_name = os.path.basename(sys.argv[0]).split('.')[0]
cwd = os.getcwd()
model_dir = os.path.join(cwd, 'checkpoints', date_string)
try:
    if not os.path.isdir(model_dir):
        os.makedirs(model_dir)
except:
    sys.exit("Could not create model directory.")

# Save hyperparameter settings as json file
with open(os.path.join(model_dir, 'hyperparameter.json'), 'w') as fp:
    json.dump(settings, fp)

######################### DATA FETCH ####################################

data = util.fetch.csv()
data['title'] = data['title'].str.lower()
data = util.fetch.csv().drop_duplicates('title').sort_values(['clicks'])

rows = len(data)

tops = data[floor(rows - rows * settings['ratio']):]
bottoms = data[:floor(rows * settings['ratio'])]

tops['label'] = 1
bottoms['label'] = 0

shuffled_tops = tops.sample(frac=1).reset_index(drop=True)
shuffled_bottoms = bottoms.sample(frac=1).reset_index(drop=True)

kvantile_size = len(tops)

test_index = kvantile_size - (kvantile_size // 5) * 2
val_index = kvantile_size - kvantile_size // 5

train_top = shuffled_tops[:test_index]
val_top = shuffled_tops[test_index:val_index]
test_top = shuffled_tops[val_index:]

train_bottom = shuffled_bottoms[:test_index]
val_bottom = shuffled_bottoms[test_index:val_index]
test_bottom = shuffled_bottoms[val_index:]

test_data = pandas.concat([test_top, test_bottom])
val_data = pandas.concat([val_top, val_bottom])
train_data = pandas.concat([train_top, train_bottom])

labeled_data = pandas.concat([test_data, train_data, val_data])

titles = labeled_data['title']
labels = labeled_data['label']

# char indice mapping
chars = {}
for title in titles:
    for char in title:
        if char in chars:
            chars[char] += 1
        # elif char.isalpha() or char == ' ' or char.isdigit():
        else:
            chars[char] = 1
chars = {k: v for k, v in chars.items() if v > settings['char_count_threshold'] }
max_features = len(chars)
print('total chars:', max_features)
char_indices = dict((c, i + 1) for i, c in enumerate(chars))
indices_char = dict((i + 1, c) for i, c in enumerate(chars))

settings['title_max_len'] = 128

# strings to indices
def strings_to_indices(strings, char_indices, max_len):
    X = []
    for i, string in enumerate(strings):
        X.append([])
        for j, char in enumerate(string[-max_len:]):
            if char in char_indices:
                X[i].append(char_indices[char])
    padded_X = sequence.pad_sequences(X, maxlen=max_len)
    return padded_X
X_train = strings_to_indices(train_data['title'], char_indices, settings['title_max_len'])
X_val = strings_to_indices(val_data['title'], char_indices, settings['title_max_len'])
X_test = strings_to_indices(test_data['title'], char_indices, settings['title_max_len'])
y_train = numpy.array(train_data['label'])
y_val = numpy.array(val_data['label'])
y_test = numpy.array(test_data['label'])

# data set validation
print("Training data positive labels: %.2f%%" % (sum(y_train) / len(y_train) * 100))
print("Validation data positive labels: %.2f%%" % (sum(y_val) / len(y_val) * 100))
print("Testing data positive labels: %.2f%%" % (sum(y_test) / len(y_test) * 100))
print('Sample chars in X:{}'.format(X_train[12]))
print('y:{}'.format(y_train[12]))

# the model
model = Sequential()
model.add(Embedding(len(chars) + 2, 1, input_length=settings['title_max_len'], mask_zero=True))
# model.add(Convolution1D(nb_filter=settings['title_max_len'], filter_length=3, border_mode='same', activation='relu'))
# model.add(MaxPooling1D(pool_length=2))
# model.add(LSTM(16, return_sequences=True))
# model.add(Dropout(0.3))
# model.add(LSTM(16, return_sequences=True))
# model.add(Dropout(0.1))
model.add((LSTM(settings['lstm'])))
model.add(Dropout(settings['dropout']))
# model.add(LSTM(1))
# model.add(Dropout(0.3))
# model.add(Bidirectional(LSTM(16, return_sequences=True)))
# model.add(Dropout(0.2))
# model.add(Bidirectional(LSTM(16, return_sequences=True)))
# model.add(Dropout(0.2))
# model.add(LSTM(100))
# model.add(Dropout(0.2))
# model.add(Dense(2, activation='sigmoid'))
model.add(Dense(1, activation='sigmoid'))
model.compile(loss='binary_crossentropy', optimizer='adam', metrics=['accuracy'])
print(model.summary())

# callbacks
# learning rate reduction
reduce_lr = ReduceLROnPlateau(
    monitor='val_loss',
    factor=0.2,
    patience=1,
    min_lr=0.001
)
checkpointer = ModelCheckpoint(
    model_dir+'/'+file_name+'.{epoch:02d}-{val_loss:.2f}.hdf5',
    monitor='val_loss',
    verbose=0,
    save_best_only=True,
    mode='min'
)
# early stopping
early_stopping = EarlyStopping(monitor='val_loss', patience=2)
# batch history
class LossHistory(keras.callbacks.Callback):
    def on_train_begin(self, logs={}):
        self.losses = []
        self.accs = []

    def on_batch_end(self, batch, logs={}):
        self.losses.append(logs.get('loss'))
        self.accs.append(logs.get('acc'))
batch_history = LossHistory()

# fit model
epoch_history = model.fit(
    X_train,
    y_train,
    nb_epoch=settings['epochs'],
    batch_size=settings['batch_size'],
    shuffle=True,
    validation_data=(X_val, y_val),
    callbacks=[checkpointer, batch_history, TensorBoard(log_dir='/tmp/rnn/' + date_string)]
)
scores = model.evaluate(X_test, y_test, verbose=0)
print("Accuracy: %.2f%%" % (scores[1]*100))

# confusion matrix
y_predict = model.predict_classes(X_test)
conf_matrix = confusion_matrix(y_test, y_predict)
print("\nConfusion matrix: ")
print(conf_matrix)

# plot model
#layer = model.layers[-2]
#f = K.function([model.layers[0].input, K.learning_phase()],
#               [layer.output])
#dense_layer_data = pandas.DataFrame(f([X_val, 0])[0])
#dense_layer_data[3] = model.predict(X_val)

#util.plot.dense_layer(dense_layer_data, model_dir)
util.plot.epochs(epoch_history, model_dir)
util.plot.batches(batch_history, model_dir)
