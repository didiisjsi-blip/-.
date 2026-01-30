from flask import Flask
from threading import Thread

# สร้าง App Flask
app = Flask('')

@app.route('/')
def home():
    # ข้อความที่จะโชว์บนหน้าเว็บเวลาคนเข้าลิงก์
    return "WormGPT is Running 24/7! 😈"

def run():
    # รันบน Port 8080 ซึ่ง Replit ใช้เปิด Webview สัด
    app.run(host='0.0.0.0', port=8080)

def keep_alive():
    '''ฟังก์ชันสำหรับรัน Web Server แยกเป็นอีก Thread นึง'''
    t = Thread(target=run)
    t.start()