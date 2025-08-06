from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from typing import List
from datetime import timedelta

from .database import get_db, engine
from .models import Base, User, Product, Order, OrderItem, UserRole
from .schemas import UserCreate, User as UserSchema, UserLogin, Token, ProductCreate, Product as ProductSchema, OrderCreate, Order as OrderSchema
from .auth import get_password_hash, verify_password, create_access_token, get_current_active_user, require_role, ACCESS_TOKEN_EXPIRE_MINUTES

# Create database tables
Base.metadata.create_all(bind=engine)

app = FastAPI(title="Yuki E-commerce API", version="1.0.0")

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def read_root():
    return {"message": "Yuki E-commerce API"}

# Authentication endpoints
@app.post("/auth/register", response_model=Token)
def register(user: UserCreate, db: Session = Depends(get_db)):
    # Check if user already exists
    db_user = db.query(User).filter(User.email == user.email).first()
    if db_user:
        raise HTTPException(status_code=400, detail="Email already registered")
    
    db_username = db.query(User).filter(User.username == user.username).first()
    if db_username:
        raise HTTPException(status_code=400, detail="Username already taken")
    
    # Create new user
    hashed_password = get_password_hash(user.password)
    db_user = User(
        email=user.email,
        username=user.username,
        hashed_password=hashed_password,
        role=user.role
    )
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    
    # Create access token
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.email}, expires_delta=access_token_expires
    )
    
    return {"access_token": access_token, "token_type": "bearer", "user": db_user}

@app.post("/auth/login", response_model=Token)
def login(user_credentials: UserLogin, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == user_credentials.email).first()
    if not user or not verify_password(user_credentials.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.email}, expires_delta=access_token_expires
    )
    
    return {"access_token": access_token, "token_type": "bearer", "user": user}

@app.get("/auth/me", response_model=UserSchema)
def get_current_user_info(current_user: User = Depends(get_current_active_user)):
    return current_user

# Product endpoints
@app.get("/products", response_model=List[ProductSchema])
def get_products(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    products = db.query(Product).filter(Product.is_active == True).offset(skip).limit(limit).all()
    return products

@app.get("/products/{product_id}", response_model=ProductSchema)
def get_product(product_id: int, db: Session = Depends(get_db)):
    product = db.query(Product).filter(Product.id == product_id).first()
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")
    return product

@app.post("/products", response_model=ProductSchema)
def create_product(product: ProductCreate, current_user: User = Depends(require_role(UserRole.ADMIN)), db: Session = Depends(get_db)):
    db_product = Product(**product.dict())
    db.add(db_product)
    db.commit()
    db.refresh(db_product)
    return db_product

@app.put("/products/{product_id}", response_model=ProductSchema)
def update_product(product_id: int, product: ProductCreate, current_user: User = Depends(require_role(UserRole.ADMIN)), db: Session = Depends(get_db)):
    db_product = db.query(Product).filter(Product.id == product_id).first()
    if db_product is None:
        raise HTTPException(status_code=404, detail="Product not found")
    
    for key, value in product.dict().items():
        setattr(db_product, key, value)
    
    db.commit()
    db.refresh(db_product)
    return db_product

@app.delete("/products/{product_id}")
def delete_product(product_id: int, current_user: User = Depends(require_role(UserRole.ADMIN)), db: Session = Depends(get_db)):
    db_product = db.query(Product).filter(Product.id == product_id).first()
    if db_product is None:
        raise HTTPException(status_code=404, detail="Product not found")
    
    db_product.is_active = False
    db.commit()
    return {"message": "Product deleted"}

# Order endpoints
@app.post("/orders", response_model=OrderSchema)
def create_order(order: OrderCreate, current_user: User = Depends(get_current_active_user), db: Session = Depends(get_db)):
    db_order = Order(
        user_id=current_user.id,
        total_amount=order.total_amount,
        shipping_address=order.shipping_address,
        status=order.status
    )
    db.add(db_order)
    db.commit()
    db.refresh(db_order)
    
    # Add order items
    for item in order.items:
        db_item = OrderItem(
            order_id=db_order.id,
            product_id=item.product_id,
            quantity=item.quantity,
            price=item.price
        )
        db.add(db_item)
    
    db.commit()
    db.refresh(db_order)
    return db_order

@app.get("/orders", response_model=List[OrderSchema])
def get_orders(current_user: User = Depends(get_current_active_user), db: Session = Depends(get_db)):
    if current_user.role in [UserRole.SUPER_ADMIN, UserRole.ADMIN]:
        orders = db.query(Order).all()
    else:
        orders = db.query(Order).filter(Order.user_id == current_user.id).all()
    return orders

@app.get("/orders/{order_id}", response_model=OrderSchema)
def get_order(order_id: int, current_user: User = Depends(get_current_active_user), db: Session = Depends(get_db)):
    order = db.query(Order).filter(Order.id == order_id).first()
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")
    
    if current_user.role not in [UserRole.SUPER_ADMIN, UserRole.ADMIN] and order.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not enough permissions")
    
    return order

@app.put("/orders/{order_id}/status")
def update_order_status(order_id: int, status: str, current_user: User = Depends(require_role(UserRole.ADMIN)), db: Session = Depends(get_db)):
    order = db.query(Order).filter(Order.id == order_id).first()
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")
    
    order.status = status
    db.commit()
    return {"message": "Order status updated"}

# User management (admin only)
@app.get("/users", response_model=List[UserSchema])
def get_users(current_user: User = Depends(require_role(UserRole.SUPER_ADMIN)), db: Session = Depends(get_db)):
    users = db.query(User).all()
    return users

@app.put("/users/{user_id}/role")
def update_user_role(user_id: int, role: UserRole, current_user: User = Depends(require_role(UserRole.SUPER_ADMIN)), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    
    user.role = role
    db.commit()
    return {"message": "User role updated"}