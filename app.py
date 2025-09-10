from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import requests
import os
from datetime import datetime, timedelta
import json
from dotenv import load_dotenv

# Carrega variáveis de ambiente
load_dotenv()

app = Flask(__name__)
CORS(app)

# Configurações do PagBank
PAGBANK_TOKEN = os.getenv("PAGBANK_TOKEN", "SEU_TOKEN_SANDBOX_AQUI")
PAGBANK_ENV = os.getenv("PAGBANK_ENV", "sandbox")
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "https://seu-site.com/webhook-pagbank")

# URLs da API baseadas no ambiente
if PAGBANK_ENV == "sandbox":
    URL_API = "https://sandbox.api.pagseguro.com/orders"
else:
    URL_API = "https://api.pagseguro.com/orders"

# Configuração MongoDB (opcional com fallback)
MONGODB_URI = os.getenv("MONGODB_URI")
client = None
db = None
pedidos_collection = None

if MONGODB_URI:
    try:
        from pymongo import MongoClient
        from bson import ObjectId
        client = MongoClient(MONGODB_URI, serverSelectionTimeoutMS=5000)
        client.admin.command('ping')
        db = client['delmonte_pizzaria']
        pedidos_collection = db['pedidos']
        print("✅ MongoDB conectado!")
    except Exception as e:
        print(f"⚠️ MongoDB indisponível: {str(e)}")
        client = None
        db = None
        pedidos_collection = None
else:
    print("⚠️ MONGODB_URI não configurada")

# Fallback para lista em memória se MongoDB não disponível
pedidos_confirmados = []

# Função auxiliar para converter ObjectId para string
def serialize_pedido(pedido):
    if pedido and '_id' in pedido:
        pedido['_id'] = str(pedido['_id'])
    return pedido

# Função para salvar pedido (MongoDB ou memória)
def salvar_pedido(pedido):
    if pedidos_collection:
        try:
            resultado = pedidos_collection.insert_one(pedido)
            return resultado.inserted_id is not None
        except Exception as e:
            print(f"Erro ao salvar no MongoDB: {e}")
            pedidos_confirmados.append(pedido)
            return True
    else:
        pedidos_confirmados.append(pedido)
        return True

# Função para listar pedidos (MongoDB ou memória)
def listar_pedidos():
    if pedidos_collection:
        try:
            pedidos = list(pedidos_collection.find().sort("created_at", -1))
            return [serialize_pedido(p) for p in pedidos]
        except Exception as e:
            print(f"Erro ao buscar no MongoDB: {e}")
            return pedidos_confirmados
    else:
        return pedidos_confirmados

# Função para atualizar status (MongoDB ou memória)
def atualizar_status_pedido_db(order_id, novo_status):
    if pedidos_collection:
        try:
            resultado = pedidos_collection.update_one(
                {"id": order_id},
                {"$set": {"status": novo_status, "updated_at": datetime.now().isoformat()}}
            )
            if resultado.matched_count > 0:
                return pedidos_collection.find_one({"id": order_id})
            return None
        except Exception as e:
            print(f"Erro ao atualizar no MongoDB: {e}")
            # Fallback para memória
            for pedido in pedidos_confirmados:
                if pedido["id"] == order_id:
                    pedido["status"] = novo_status
                    pedido["updated_at"] = datetime.now().isoformat()
                    return pedido
            return None
    else:
        for pedido in pedidos_confirmados:
            if pedido["id"] == order_id:
                pedido["status"] = novo_status
                pedido["updated_at"] = datetime.now().isoformat()
                return pedido
        return None

# ROTAS PARA SERVIR ARQUIVOS HTML
@app.route("/")
def home_page():
    try:
        return send_from_directory('.', 'index.html')
    except:
        return jsonify({
            "status": "API PagBank DEL MONTE funcionando!",
            "ambiente": PAGBANK_ENV,
            "endpoints": [
                "GET / - Página inicial",
                "GET /index.html - Página inicial", 
                "GET /pagamento.html - Página de pagamento",
                "GET /pedidos.html - Gestão de pedidos",
                "POST /criar-pedido - Criar pedido PIX",
                "POST /criar-pedido-cartao - Criar pedido com cartão",
                "GET /status-pedido/<order_id> - Consultar status",
                "POST /webhook-pagbank - Receber notificações"
            ]
        })

@app.route("/index.html")
def index_page():
    return send_from_directory('.', 'index.html')

@app.route("/pagamento.html")
def pagamento_page():
    return send_from_directory('.', 'pagamento.html')

@app.route("/pedidos.html")
def pedidos_page():
    return send_from_directory('.', 'pedidos.html')

# ROTAS DA API
@app.route("/api", methods=["GET"])
def api_info():
    mongodb_status = "Conectado" if pedidos_collection else "Desconectado"
    storage_type = "MongoDB" if pedidos_collection else "Memória RAM"
    
    return jsonify({
        "status": "API PagBank DEL MONTE funcionando!",
        "ambiente": PAGBANK_ENV,
        "mongodb_status": mongodb_status,
        "storage_type": storage_type,
        "endpoints": [
            "GET / - Página inicial",
            "GET /index.html - Página inicial",
            "GET /pagamento.html - Página de pagamento", 
            "GET /pedidos.html - Gestão de pedidos",
            "POST /criar-pedido - Criar pedido PIX",
            "POST /criar-pedido-cartao - Criar pedido com cartão",
            "GET /status-pedido/<order_id> - Consultar status",
            "POST /webhook-pagbank - Receber notificações",
            "GET /api/pedidos - Listar pedidos",
            "PUT /api/pedidos/<order_id>/status - Atualizar status"
        ]
    })

@app.route("/api/pedidos", methods=["GET"])
def api_listar_pedidos():
    try:
        pedidos = listar_pedidos()
        return jsonify({
            "sucesso": True,
            "pedidos": pedidos,
            "total": len(pedidos),
            "storage": "MongoDB" if pedidos_collection else "Memória"
        }), 200
    except Exception as e:
        return jsonify({"erro": f"Erro interno: {str(e)}"}), 500

@app.route("/api/pedidos/<order_id>/status", methods=["PUT"])
def api_atualizar_status_pedido(order_id):
    try:
        dados = request.json
        novo_status = dados.get("status")
        
        if novo_status not in ["pending", "preparing", "completed", "delivered"]:
            return jsonify({"erro": "Status inválido"}), 400
        
        pedido = atualizar_status_pedido_db(order_id, novo_status)
        
        if not pedido:
            return jsonify({"erro": "Pedido não encontrado"}), 404
        
        return jsonify({
            "sucesso": True,
            "pedido": serialize_pedido(pedido) if pedidos_collection else pedido,
            "mensagem": f"Status atualizado para {novo_status}"
        }), 200
        
    except Exception as e:
        return jsonify({"erro": f"Erro interno: {str(e)}"}), 500

@app.route("/api/pedidos/stats", methods=["GET"])
def estatisticas_pedidos():
    try:
        pedidos = listar_pedidos()
        hoje = datetime.now().date().isoformat()
        
        # Filtros usando Python (funciona para MongoDB e memória)
        pedidos_hoje = [p for p in pedidos if p.get("created_at", "").startswith(hoje)]
        pendentes = [p for p in pedidos if p.get("status") == "pending"]
        preparando = [p for p in pedidos if p.get("status") == "preparing"]
        
        receita_hoje = sum(p.get("total", 0) for p in pedidos_hoje)
        
        return jsonify({
            "sucesso": True,
            "stats": {
                "pedidos_hoje": len(pedidos_hoje),
                "pendentes": len(pendentes),
                "preparando": len(preparando),
                "receita_hoje": receita_hoje
            }
        }), 200
        
    except Exception as e:
        return jsonify({"erro": f"Erro interno: {str(e)}"}), 500

def processar_pedido_confirmado(order_data, payment_method, payment_status):
    try:
        pedido = {
            "id": order_data.get("reference_id", f"DELMONTE_{int(datetime.now().timestamp())}"),
            "customer": {
                "name": order_data.get("customer", {}).get("name", "Cliente"),
                "email": order_data.get("customer", {}).get("email", ""),
                "phone": order_data.get("customer", {}).get("phone", ""),
                "tax_id": order_data.get("customer", {}).get("tax_id", "")
            },
            "delivery_address": order_data.get("delivery_address", {}),
            "items": order_data.get("items", []),
            "subtotal": (order_data.get("total_amount", 0) - order_data.get("delivery_fee", 0)) / 100,
            "delivery_fee": order_data.get("delivery_fee", 0) / 100,
            "total": order_data.get("total_amount", 0) / 100,
            "payment_method": payment_method,
            "payment_status": payment_status,
            "status": "pending",
            "created_at": datetime.now().isoformat(),
            "paid_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat()
        }
        
        sucesso = salvar_pedido(pedido)
        storage = "MongoDB" if pedidos_collection else "memória"
        
        if sucesso:
            print(f"✅ Pedido salvo em {storage}: {pedido['id']}")
            return True
        else:
            print(f"❌ Erro ao salvar pedido em {storage}")
            return False
        
    except Exception as e:
        print(f"❌ Erro ao processar pedido confirmado: {str(e)}")
        return False

@app.route("/criar-pedido", methods=["POST"])
def criar_pedido_pix():
    try:
        dados = request.json

        if not dados or not dados.get("items"):
            return jsonify({"erro": "Dados do pedido inválidos"}), 400

        total_amount = dados.get("total_amount", 0)
        if total_amount == 0:
            for item in dados.get("items", []):
                total_amount += item.get("unit_amount", 0) * item.get("quantity", 1)

        expiration_date = (datetime.now() + timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M:%S-03:00")

        pedido = {
            "reference_id": dados.get("reference_id", f"DELMONTE_{int(datetime.now().timestamp())}"),
            "customer": {
                "name": dados.get("customer", {}).get("name", "Cliente DEL MONTE"),
                "email": dados.get("customer", {}).get("email", "cliente@delmonte.com"),
                "tax_id": dados.get("customer", {}).get("tax_id", "12345678901"),
                "phones": [{"country": "55", "area": "21", "number": "999999999", "type": "MOBILE"}]
            },
            "items": [
                {
                    "reference_id": f"item_{i}",
                    "name": item["name"][:100],
                    "quantity": item["quantity"],
                    "unit_amount": item["unit_amount"]
                }
                for i, item in enumerate(dados.get("items", []))
            ],
            "qr_codes": [{"amount": {"value": total_amount}, "expiration_date": expiration_date}],
            "notification_urls": [WEBHOOK_URL]
        }

        headers = {
            "Authorization": f"Bearer {PAGBANK_TOKEN}",
            "Content-Type": "application/json",
            "Accept": "application/json"
        }

        response = requests.post(URL_API, json=pedido, headers=headers)

        if response.status_code in [200, 201]:
            response_data = response.json()

            qr_code_info = {}
            if "qr_codes" in response_data and len(response_data["qr_codes"]) > 0:
                qr_code = response_data["qr_codes"][0]
                qr_code_info = {
                    "qr_code_text": qr_code.get("text", ""),
                    "qr_code_link": qr_code.get("links", [{}])[0].get("href", "") if qr_code.get("links") else "",
                    "expiration_date": qr_code.get("expiration_date", "")
                }

            return jsonify({
                "sucesso": True,
                "order_id": response_data.get("id"),
                "reference_id": response_data.get("reference_id"),
                "qr_code": qr_code_info,
                "status": "WAITING",
                "mensagem": "Pedido criado com sucesso! Aguardando pagamento."
            }), 201
        else:
            return jsonify({
                "erro": "Erro ao criar pedido no PagBank",
                "detalhes": response.json() if response.text else "Sem detalhes",
                "status_code": response.status_code
            }), response.status_code

    except Exception as e:
        return jsonify({"erro": f"Erro interno: {str(e)}"}), 500

@app.route("/criar-pedido-cartao", methods=["POST"])
def criar_pedido_cartao():
    try:
        dados = request.json

        card_data = dados.get("card_data", {})
        if not all([card_data.get("number"), card_data.get("holder"),
                   card_data.get("exp_month"), card_data.get("exp_year"),
                   card_data.get("security_code")]):
            return jsonify({"erro": "Dados do cartão incompletos"}), 400

        total_amount = dados.get("total_amount", 0)
        if total_amount == 0:
            for item in dados.get("items", []):
                total_amount += item.get("unit_amount", 0) * item.get("quantity", 1)

        payment_type = dados.get("payment_type", "credit")
        installments = dados.get("installments", 1)
        card_type = "CREDIT_CARD"

        payment_method = {
            "type": card_type,
            "installments": installments,
            "capture": True,
            "card": {
                "number": card_data["number"],
                "exp_month": card_data["exp_month"],
                "exp_year": card_data["exp_year"],
                "security_code": card_data["security_code"],
                "holder": {"name": card_data["holder"]},
                "store": False
            }
        }

        pedido = {
            "reference_id": dados.get("reference_id", f"DELMONTE_{int(datetime.now().timestamp())}"),
            "customer": {
                "name": dados.get("customer", {}).get("name", "Cliente DEL MONTE"),
                "email": dados.get("customer", {}).get("email", "cliente@delmonte.com"),
                "tax_id": dados.get("customer", {}).get("tax_id", "12345678901"),
                "phones": [{"country": "55", "area": "21", "number": "999999999", "type": "MOBILE"}]
            },
            "items": [
                {
                    "reference_id": f"item_{i}",
                    "name": item["name"][:100],
                    "quantity": item["quantity"],
                    "unit_amount": item["unit_amount"]
                }
                for i, item in enumerate(dados.get("items", []))
            ],
            "charges": [
                {
                    "reference_id": f"charge_{payment_type}",
                    "description": f"Pedido Pizzaria DEL MONTE - {payment_type.upper()}",
                    "amount": {"value": total_amount, "currency": "BRL"},
                    "payment_method": payment_method
                }
            ],
            "notification_urls": [WEBHOOK_URL]
        }

        headers = {
            "Authorization": f"Bearer {PAGBANK_TOKEN}",
            "Content-Type": "application/json",
            "Accept": "application/json"
        }

        response = requests.post(URL_API, json=pedido, headers=headers)

        if response.status_code in [200, 201]:
            response_data = response.json()

            charge_status = "UNKNOWN"
            if "charges" in response_data and len(response_data["charges"]) > 0:
                charge_status = response_data["charges"][0].get("status", "UNKNOWN")

            if charge_status == "PAID":
                processar_pedido_confirmado(dados, payment_type.upper(), "PAID")
                
                return jsonify({
                    "sucesso": True,
                    "order_id": response_data.get("id"),
                    "reference_id": response_data.get("reference_id"),
                    "status": charge_status,
                    "mensagem": f"Pagamento aprovado no {payment_type}!",
                    "installments": installments,
                    "dados": response_data
                }), 201
            else:
                return jsonify({
                    "sucesso": False,
                    "erro": f"Pagamento não autorizado. Status: {charge_status}",
                    "detalhes": response_data.get("charges", [{}])[0].get("payment_response", {}) if response_data.get("charges") else {}
                }), 400
        else:
            error_data = response.json() if response.text else {}
            return jsonify({
                "erro": "Erro ao processar pagamento com cartão",
                "detalhes": error_data,
                "status_code": response.status_code
            }), response.status_code

    except Exception as e:
        return jsonify({"erro": f"Erro interno: {str(e)}"}), 500

@app.route("/status-pedido/<order_id>", methods=["GET"])
def consultar_status(order_id):
    try:
        headers = {
            "Authorization": f"Bearer {PAGBANK_TOKEN}",
            "Content-Type": "application/json",
            "Accept": "application/json"
        }

        response = requests.get(f"{URL_API}/{order_id}", headers=headers)

        if response.status_code == 200:
            data = response.json()

            status = "UNKNOWN"
            payment_method = "UNKNOWN"

            if data.get("charges"):
                charge = data["charges"][0]
                status = charge.get("status", "UNKNOWN")
                payment_method = charge.get("payment_method", {}).get("type", "CARD")
            elif data.get("qr_codes"):
                if data.get("charges") and len(data["charges"]) > 0:
                    status = data["charges"][0].get("status", "WAITING")
                else:
                    status = "WAITING"
                payment_method = "PIX"

            return jsonify({
                "order_id": data.get("id"),
                "reference_id": data.get("reference_id"),
                "status": status,
                "payment_method": payment_method,
                "created_at": data.get("created_at"),
                "customer": data.get("customer", {}).get("name"),
                "total": sum(item.get("unit_amount", 0) * item.get("quantity", 0) for item in data.get("items", []))
            }), 200
        else:
            return jsonify({
                "erro": "Pedido não encontrado",
                "detalhes": response.json() if response.text else "Sem detalhes"
            }), response.status_code

    except Exception as e:
        return jsonify({"erro": f"Erro interno: {str(e)}"}), 500

@app.route("/webhook-pagbank", methods=["POST"])
def webhook_pagbank():
    try:
        dados = request.json

        if dados and dados.get("charges"):
            charge = dados["charges"][0]
            status = charge.get("status")
            reference_id = dados.get("reference_id")
            payment_method = charge.get("payment_method", {}).get("type", "UNKNOWN")

            if status == "PAID":
                order_data = {
                    "reference_id": reference_id,
                    "customer": dados.get("customer", {}),
                    "items": dados.get("items", []),
                    "total_amount": sum(item.get("unit_amount", 0) * item.get("quantity", 0) 
                                      for item in dados.get("items", [])),
                    "delivery_fee": 500
                }
                
                processar_pedido_confirmado(order_data, payment_method, "PAID")

        return jsonify({"status": "webhook processado"}), 200
    except Exception as e:
        return jsonify({"erro": str(e)}), 500

@app.route("/config", methods=["GET"])
def get_config():
    return jsonify({
        "ambiente": PAGBANK_ENV,
        "moeda": "BRL",
        "pix_expiracao_minutos": 30,
        "aceita_cartao": True,
        "aceita_pix": True,
        "max_parcelas": 6,
        "mongodb_status": "Conectado" if pedidos_collection else "Desconectado",
        "storage_type": "MongoDB" if pedidos_collection else "Memória RAM"
    })

if __name__ == "__main__":
    if PAGBANK_TOKEN == "SEU_TOKEN_SANDBOX_AQUI":
        print("⚠️  ATENÇÃO: Configure seu token do PagBank no arquivo .env!")
    else:
        print(f"✅ Token PagBank configurado!")
        print(f"📍 Ambiente: {PAGBANK_ENV}")
    
    storage_info = "MongoDB Atlas" if pedidos_collection else "Memória RAM (temporário)"
    print(f"💾 Armazenamento: {storage_info}")
    print("🍕 API DEL MONTE rodando em http://localhost:5000")
    app.run(port=5000, debug=True)