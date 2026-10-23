import os

# The saved .h5 models need Keras 2 (tf-keras) to load. TensorFlow reads this
# variable on first import, so it must be set before any tensorflow import.
os.environ["TF_USE_LEGACY_KERAS"] = "1"
