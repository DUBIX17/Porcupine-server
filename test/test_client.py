import os
import sys
import time
import wave
import requests

SERVER = os.getenv('SERVER_URL', 'http://localhost:10000')

def start_session():
    r = requests.post(SERVER + '/session/start')
    r.raise_for_status()
    return r.json()

def stream_wav(filepath, session):
    wf = wave.open(filepath, 'rb')
    assert wf.getnchannels() == 1
    assert wf.getsampwidth() == 2
    assert wf.getframerate() == session['sampleRate']
    frame_len = session['frameLength']
    bytes_per_frame = frame_len * 2
    url = SERVER + '/audio?sessionId=' + session['sessionId']

    print('Streaming to', url)
    while True:
        data = wf.readframes(frame_len)
        if not data:
            break
        r = requests.post(url, data=data, headers={'Content-Type':'application/octet-stream'})
        if r.status_code != 200:
            print('server error', r.status_code, r.text); break
        j = r.json()
        if j.get('detected'):
            print('Wake word detected!')
            break
        time.sleep(0.01)
    wf.close()

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print('Usage: python test_client.py path/to/16k_mono_pcm.wav')
        sys.exit(1)
    session = start_session()
    print('Session:', session)
    stream_wav(sys.argv[1], session)
