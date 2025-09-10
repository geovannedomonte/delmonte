from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import requests
import os
from datetime import datetime, timedelta
import json
from dotenv import load_dotenv
from pymongo import MongoClient
from bson import ObjectId

# Carrega variáveis de ambiente
load_dotenv()

app = Flask(__name__)
CORS(app)  # Permite requisições do frontend

# Configurações do PagBank
PAGBANK_TOKEN = os.getenv("PAGBANK_TOKEN", "SEU_TOKEN_SANDBOX_AQUI")
PAGBANK_ENV = os.getenv("PAGBANK_ENV", "sandbox")
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "https://seu-site.com/webhook-pagbank")

# Configuração MongoDB
MONGODB_URI = os.getenv("MONGODB_URI")

# URLs da API baseadas no ambiente
if PAGBANK_ENV == "sandbox":
    URL_API = "https://sandbox.api.pagseguro.com/orders"
else:
    URL_API = "https://api.pagseguro.com/orders"

# Conexão MongoDB
try:
    client = MongoClient(MONGODB_URI)
    db = client['delmonte_pizzaria']
    pedidos_collection = db['pedidos']
    print("✅ Conectado ao MongoDB Atlas!")
except Exception as e:
    print(f"❌ Erro ao conectar MongoDB: {str(e)}")
    client = None
    db = None
    pedidos_collection = None

# Função auxiliar para converter ObjectId para string
def serialize_pedido(pedido):
    if pedido and '_id' in pedido:
        pedido['_id'] = str(pedido['_id'])
    return pedido

# ROTAS PARA SERVIR ARQUIVOS HTML
@app.route("/")
def home_page():
    """Serve a página inicial (index.html)"""
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
    """Serve a página inicial"""
    return send_from_directory('.', 'index.html')

@app.route("/pagamento.html")
def pagamento_page():
    """Serve a página de pagamento"""
    return send_from_directory('.', 'pagamento.html')

@app.route("/pedidos.html")
def pedidos_page():
    """Serve a página de gestão de pedidos"""
    return send_from_directory('.', 'pedidos.html')

# ROTAS DA API
@app.route("/api", methods=["GET"])
def api_info():
    return jsonify({
        "status": "API PagBank DEL MONTE funcionando!",
        "ambiente": PAGBANK_ENV,
        "mongodb_status": "Conectado" if pedidos_collection else "Desconectado",
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
def listar_pedidos():
    """Lista todos os pedidos confirmados"""
    try:
        if not pedidos_collection:
            return jsonify({"erro": "MongoDB não conectado"}), 500
        
        # Buscar todos os pedidos, ordenados por data de criação (mais recentes primeiro)
        pedidos = list(pedidos_collection.find().sort("created_at", -1))
        
        # Converter ObjectId para string
        pedidos_serializados = [serialize_pedido(pedido) for pedido in pedidos]
        
        return jsonify({
            "sucesso": True,
            "pedidos": pedidos_serializados
        }), 200
    except Exception as e:
        return jsonify({"erro": f"Erro interno: {str(e)}"}), 500

@app.route("/api/pedidos/<order_id>/status", methods=["PUT"])
def atualizar_status_pedido(order_id):
    """Atualiza o status de um pedido"""
    try:
        if not pedidos_collection:
            return jsonify({"erro": "MongoDB não conectado"}), 500
            
        dados = request.json
        novo_status = dados.get("status")
        
        if novo_status not in ["pending", "preparing", "completed", "delivered"]:
            return jsonify({"erro": "Status inválido"}), 400
        
        # Atualizar pedido no MongoDB
        resultado = pedidos_collection.update_one(
            {"id": order_id},
            {
                "$set": {
                    "status": novo_status,
                    "updated_at": datetime.now().isoformat()
                }
            }
        )
        
        if resultado.matched_count == 0:
            return jsonify({"erro": "Pedido não encontrado"}), 404
        
        # Buscar pedido atualizado
        pedido = pedidos_collection.find_one({"id": order_id})
        pedido_serializado = serialize_pedido(pedido)
        
        return jsonify({
            "sucesso": True,
            "pedido": pedido_serializado,
            "mensagem": f"Status atualizado para {novo_status}"
        }), 200
        
    except Exception as e:
        return jsonify({"erro": f"Erro interno: {str(e)}"}), 500

@app.route("/api/pedidos/stats", methods=["GET"])
def estatisticas_pedidos():
    """Retorna estatísticas dos pedidos"""
    try:
        if not pedidos_collection:
            return jsonify({"erro": "MongoDB não conectado"}), 500
        
        hoje = datetime.now().date()
        hoje_str = hoje.isoformat()
        
        # Contadores usando agregação MongoDB
        pipeline_hoje = [
            {"$match": {"created_at": {"$regex": f"^{hoje_str}"}}},
            {"$count": "total"}
        ]
        
        pipeline_pendentes = [
            {"$match": {"status": "pending"}},
            {"$count": "total"}
        ]
        
        pipeline_preparando = [
            {"$match": {"status": "preparing"}},
            {"$count": "total"}
        ]
        
        pipeline_receita = [
            {"$match": {"created_at": {"$regex": f"^{hoje_str}"}}},
            {"$group": {"_id": None, "total": {"$sum": "$total"}}}
        ]
        
        # Executar consultas
        total_hoje = list(pedidos_collection.aggregate(pipeline_hoje))
        pendentes = list(pedidos_collection.aggregate(pipeline_pendentes))
        preparando = list(pedidos_collection.aggregate(pipeline_preparando))
        receita = list(pedidos_collection.aggregate(pipeline_receita))
        
        return jsonify({
            "sucesso": True,
            "stats": {
                "pedidos_hoje": total_hoje[0]["total"] if total_hoje else 0,
                "pendentes": pendentes[0]["total"] if pendentes else 0,
                "preparando": preparando[0]["total"] if preparando else 0,
                "receita_hoje": receita[0]["total"] if receita else 0
            }
        }), 200
        
    except Exception as e:
        return jsonify({"erro": f"Erro interno: {str(e)}"}), 500

def processar_pedido_confirmado(order_data, payment_method, payment_status):
    """Salva um pedido confirmado no MongoDB"""
    try:
        if not pedidos_collection:
            print("❌ MongoDB não conectado - pedido não salvo")
            return False
        
        # Criar objeto do pedido
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
        
        # Salvar no MongoDB
        resultado = pedidos_collection.insert_one(pedido)
        
        if resultado.inserted_id:
            print(f"✅ Pedido salvo no MongoDB: {pedido['id']}")
            return True
        else:
            print("❌ Erro ao salvar pedido no MongoDB")
            return False
        
    except Exception as e:
        print(f"❌ Erro ao processar pedido confirmado: {str(e)}")
        return False

@app.route("/criar-pedido", methods=["POST"])
def criar_pedido_pix():
    """Cria pedido com pagamento PIX"""
    try:
        dados = request.json

        # Validação básica
        if not dados or not dados.get("items"):
            return jsonify({"erro": "Dados do pedido inválidos"}), 400

        # Calcula o total se não foi fornecido
        total_amount = dados.get("total_amount", 0)
        if total_amount == 0:
            for item in dados.get("items", []):
                total_amount += item.get("unit_amount", 0) * item.get("quantity", 1)

        # Define expiração do PIX para 30 minutos a partir de agora
        expiration_date = (datetime.now() + timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M:%S-03:00")

        # Estrutura do pedido para PagBank
        pedido = {
            "reference_id": dados.get("reference_id", f"DELMONTE_{int(datetime.now().timestamp())}"),
            "customer": {
                "name": dados.get("customer", {}).get("name", "Cliente DEL MONTE"),
                "email": dados.get("customer", {}).get("email", "cliente@delmonte.com"),
                "tax_id": dados.get("customer", {}).get("tax_id", "12345678901"),
                "phones": [
                    {
                        "country": "55",
                        "area": "21",
                        "number": "999999999",
                        "type": "MOBILE"
                    }
                ]
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
            "qr_codes": [
                {
                    "amount": {
                        "value": total_amount
                    },
                    "expiration_date": expiration_date
                }
            ],
            "notification_urls": [WEBHOOK_URL]
        }

        headers = {
            "Authorization": f"Bearer {PAGBANK_TOKEN}",
            "Content-Type": "application/json",
            "Accept": "application/json"
        }

        print(f"Enviando pedido para PagBank: {json.dumps(pedido, indent=2)}")

        response = requests.post(URL_API, json=pedido, headers=headers)

        print(f"Resposta PagBank: {response.status_code} - {response.text}")

        if response.status_code in [200, 201]:
            response_data = response.json()

            # Extrai informações do QR Code se disponível
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
        print(f"Erro interno: {str(e)}")
        return jsonify({"erro": f"Erro interno: {str(e)}"}), 500

@app.route("/criar-pedido-cartao", methods=["POST"])
def criar_pedido_cartao():
    """Cria pedido com pagamento por cartão de crédito"""
    try:
        dados = request.json

        # Validação dos dados do cartão
        card_data = dados.get("card_data", {})
        if not all([card_data.get("number"), card_data.get("holder"),
                   card_data.get("exp_month"), card_data.get("exp_year"),
                   card_data.get("security_code")]):
            return jsonify({"erro": "Dados do cartão incompletos"}), 400

        # Calcula o total
        total_amount = dados.get("total_amount", 0)
        if total_amount == 0:
            for item in dados.get("items", []):
                total_amount += item.get("unit_amount", 0) * item.get("quantity", 1)

        # Determina o tipo de cartão
        payment_type = dados.get("payment_type", "credit")
        installments = dados.get("installments", 1)

        # Para crédito
        card_type = "CREDIT_CARD"

        # Construir payment_method
        payment_method = {
            "type": card_type,
            "installments": installments,
            "capture": True,
            "card": {
                "number": card_data["number"],
                "exp_month": card_data["exp_month"],
                "exp_year": card_data["exp_year"],
                "security_code": card_data["security_code"],
                "holder": {
                    "name": card_data["holder"]
                },
                "store": False
            }
        }

        pedido = {
            "reference_id": dados.get("reference_id", f"DELMONTE_{int(datetime.now().timestamp())}"),
            "customer": {
                "name": dados.get("customer", {}).get("name", "Cliente DEL MONTE"),
                "email": dados.get("customer", {}).get("email", "cliente@delmonte.com"),
                "tax_id": dados.get("customer", {}).get("tax_id", "12345678901"),
                "phones": [
                    {
                        "country": "55",
                        "area": "21",
                        "number": "999999999",
                        "type": "MOBILE"
                    }
                ]
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
                    "amount": {
                        "value": total_amount,
                        "currency": "BRL"
                    },
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

        print(f"Enviando pedido de cartão para PagBank: {json.dumps(pedido, indent=2)}")

        response = requests.post(URL_API, json=pedido, headers=headers)

        print(f"Resposta PagBank (Cartão): {response.status_code} - {response.text}")

        if response.status_code in [200, 201]:
            response_data = response.json()

            # Verifica status do pagamento
            charge_status = "UNKNOWN"
            if "charges" in response_data and len(response_data["charges"]) > 0:
                charge_status = response_data["charges"][0].get("status", "UNKNOWN")

            if charge_status == "PAID":
                # Processar pedido confirmado
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
        print(f"Erro interno no pagamento com cartão: {str(e)}")
        return jsonify({"erro": f"Erro interno: {str(e)}"}), 500

@app.route("/status-pedido/<order_id>", methods=["GET"])
def consultar_status(order_id):
    """Consulta o status de um pedido"""
    try:
        headers = {
            "Authorization": f"Bearer {PAGBANK_TOKEN}",
            "Content-Type": "application/json",
            "Accept": "application/json"
        }

        response = requests.get(f"{URL_API}/{order_id}", headers=headers)

        if response.status_code == 200:
            data = response.json()

            # Determina o status baseado no tipo de pagamento
            status = "UNKNOWN"
            payment_method = "UNKNOWN"

            if data.get("charges"):
                # Pagamento com cartão
                charge = data["charges"][0]
                status = charge.get("status", "UNKNOWN")
                payment_method = charge.get("payment_method", {}).get("type", "CARD")
            elif data.get("qr_codes"):
                # Pagamento PIX
                qr_code = data["qr_codes"][0]
                # Para PIX, verificamos se há charges criadas
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
    """Recebe notificações do PagBank sobre mudanças no status do pagamento"""
    try:
        dados = request.json
        print(f"Webhook recebido: {json.dumps(dados, indent=2)}")

        # Extrai informações importantes
        if dados and dados.get("charges"):
            charge = dados["charges"][0]
            status = charge.get("status")
            reference_id = dados.get("reference_id")
            payment_method = charge.get("payment_method", {}).get("type", "UNKNOWN")

            # Processar pagamento confirmado
            if status == "PAID":
                print(f"✅ Pagamento confirmado para pedido {reference_id} via {payment_method}")
                
                # Buscar dados do pedido original (simplificado para PIX)
                order_data = {
                    "reference_id": reference_id,
                    "customer": dados.get("customer", {}),
                    "items": dados.get("items", []),
                    "total_amount": sum(item.get("unit_amount", 0) * item.get("quantity", 0) 
                                      for item in dados.get("items", [])),
                    "delivery_fee": 500  # R$ 5,00 padrão
                }
                
                # Salvar pedido confirmado no MongoDB
                processar_pedido_confirmado(order_data, payment_method, "PAID")
                
            elif status == "DECLINED":
                print(f"❌ Pagamento recusado para pedido {reference_id} via {payment_method}")
            elif status == "CANCELED":
                print(f"⚠️ Pagamento cancelado para pedido {reference_id} via {payment_method}")

        return jsonify({"status": "webhook processado"}), 200
    except Exception as e:
        print(f"Erro no webhook: {str(e)}")
        return jsonify({"erro": str(e)}), 500

@app.route("/config", methods=["GET"])
def get_config():
    """Retorna configurações públicas para o frontend"""
    return jsonify({
        "ambiente": PAGBANK_ENV,
        "moeda": "BRL",
        "pix_expiracao_minutos": 30,
        "aceita_cartao": True,
        "aceita_pix": True,
        "max_parcelas": 6,
        "mongodb_status": "Conectado" if pedidos_collection else "Desconectado"
    })

if __name__ == "__main__":
    # Verifica se o token foi configurado
    if PAGBANK_TOKEN == "SEU_TOKEN_SANDBOX_AQUI":
        print("⚠️  ATENÇÃO: Configure seu token do PagBank no arquivo .env!")
        print("   Crie um arquivo .env e adicione: PAGBANK_TOKEN=seu_token_aqui")
    else:
        print(f"✅ Token PagBank configurado!")
        print(f"📍 Ambiente: {PAGBANK_ENV}")
    
    if MONGODB_URI:
        print(f"✅ MongoDB URI configurado!")
    else:
        print("⚠️  MongoDB URI não configurado!")
    
    print("🍕 API DEL MONTE rodando em http://localhost:5000")
    app.run(port=5000, debug=True)