from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List, Optional
import uuid
import telebot
import time

app = FastAPI()

# Database sementara (simulasi)
users = {}
ads = []
viewed_ads = {}
referrals = {}
transactions = {}
withdraw_requests = {}

BOT_TOKEN = "7725713610:AAHhgOUkBRH1Xa1SCbiIzhQdrTk9F8ie4zI"
bot = telebot.TeleBot(BOT_TOKEN)

class User(BaseModel):
    user_id: str
    username: str
    balance: int = 0
    referred_by: Optional[str] = None
    dana_number: Optional[str] = None  # Nomor DANA pengguna

class Ad(BaseModel):
    id: str
    title: str
    description: str
    reward: int

class Transaction(BaseModel):
    user_id: str
    type: str  # "view_ad" atau "withdraw"
    amount: int
    timestamp: float

MIN_WITHDRAW_AMOUNT = 1000  # Batas minimal pencairan saldo
POINTS_TO_RUPIAH = 10  # 1.000 poin = Rp 10.000

@app.post("/register")
def register_user(user: User):
    if user.user_id in users:
        raise HTTPException(status_code=400, detail="User already exists")
    users[user.user_id] = user
    
    # Sistem Referral
    if user.referred_by and user.referred_by in users:
        users[user.referred_by].balance += 10  # Bonus referral
        referrals.setdefault(user.referred_by, []).append(user.user_id)
    
    return {"message": "User registered successfully"}

@app.post("/set_dana")
def set_dana(user_id: str, dana_number: str):
    if user_id not in users:
        raise HTTPException(status_code=404, detail="User not found")
    users[user_id].dana_number = dana_number
    return {"message": "DANA number set successfully"}

@app.get("/ads", response_model=List[Ad])
def get_ads():
    return ads

@app.post("/ads")
def create_ad(ad: Ad):
    ad.id = str(uuid.uuid4())
    ads.append(ad)
    return {"message": "Ad created successfully", "ad": ad}

@app.post("/view_ad")
def view_ad(user_id: str, ad_id: str):
    if user_id not in users:
        raise HTTPException(status_code=404, detail="User not found")
    
    ad = next((a for a in ads if a.id == ad_id), None)
    if not ad:
        raise HTTPException(status_code=404, detail="Ad not found")
    
    # Anti-Deteksi: Cek apakah user sudah melihat iklan ini dalam 10 menit terakhir
    last_view = viewed_ads.get((user_id, ad_id))
    if last_view and time.time() - last_view < 600:
        raise HTTPException(status_code=400, detail="You have already viewed this ad recently")
    
    viewed_ads[(user_id, ad_id)] = time.time()
    users[user_id].balance += ad.reward
    transactions.setdefault(user_id, []).append(Transaction(user_id=user_id, type="view_ad", amount=ad.reward, timestamp=time.time()))
    return {"message": "Ad viewed", "new_balance": users[user_id].balance}

@app.post("/withdraw")
def withdraw_balance(user_id: str, amount: int):
    if user_id not in users:
        raise HTTPException(status_code=404, detail="User not found")
    if users[user_id].balance < amount:
        raise HTTPException(status_code=400, detail="Insufficient balance")
    if amount < MIN_WITHDRAW_AMOUNT:
        raise HTTPException(status_code=400, detail=f"Minimum withdrawal amount is {MIN_WITHDRAW_AMOUNT} points")
    if not users[user_id].dana_number:
        raise HTTPException(status_code=400, detail="DANA number not set. Use /set_dana to register your DANA number.")
    
    rupiah_amount = (amount / 1000) * 10000  # Konversi poin ke rupiah
    users[user_id].balance -= amount
    transactions.setdefault(user_id, []).append(Transaction(user_id=user_id, type="withdraw", amount=-amount, timestamp=time.time()))
    withdraw_requests[user_id] = {"amount": rupiah_amount, "dana_number": users[user_id].dana_number}
    return {"message": f"Withdrawal request submitted via DANA for Rp {rupiah_amount}", "remaining_balance": users[user_id].balance}

@app.get("/transactions")
def get_transactions(user_id: str):
    if user_id not in transactions:
        return {"transactions": []}
    return {"transactions": transactions[user_id]}

@bot.message_handler(commands=['set_dana'])
def set_dana_command(message):
    user_id = str(message.chat.id)
    bot.reply_to(message, "Please enter your DANA number.")
    
    @bot.message_handler(func=lambda msg: msg.text.isdigit())
    def process_dana_number(msg):
        users[user_id].dana_number = msg.text
        bot.reply_to(msg, "Your DANA number has been registered successfully!")

@bot.message_handler(commands=['withdraw'])
def withdraw_request(message):
    user_id = str(message.chat.id)
    if user_id not in users:
        bot.reply_to(message, "You are not registered. Use /start to register.")
        return
    if not users[user_id].dana_number:
        bot.reply_to(message, "Please set your DANA number first using /set_dana.")
        return
    
    bot.reply_to(message, "Please enter the amount you want to withdraw.")
    
    @bot.message_handler(func=lambda msg: msg.text.isdigit())
    def process_withdraw(msg):
        amount = int(msg.text)
        try:
            response = withdraw_balance(user_id, amount)
            bot.reply_to(msg, f"{response['message']}! Remaining balance: {response['remaining_balance']} points")
        except HTTPException as e:
            bot.reply_to(msg, e.detail)

import threading
import uvicorn

def start_bot():
    bot.polling(none_stop=True)

threading.Thread(target=start_bot, daemon=True).start()

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
