from kokoro import KPipeline
import soundfile as sf
import numpy as np

# Initialize the pipeline. 'a' stands for American English.
# Other options include 'b' (British English), 'j' (Japanese), etc.
pipeline = KPipeline(lang_code='a')

text = "Kokoro is a tiny, open text-to-speech model that runs right here on your CPU."

# Generate audio. 'af_bella' is a built-in American Female voice.
# The pipeline yields audio in chunks.
audio_chunks = []
for _, _, chunk in pipeline(text, voice='af_bella', speed=1.0):
    audio_chunks.append(chunk)

# Concatenate the chunks into a single array
audio = np.concatenate(audio_chunks)

# Save the audio file. Kokoro natively outputs at 24kHz.
sf.write("output.wav", audio, 24000)
print("Audio saved to output.wav")