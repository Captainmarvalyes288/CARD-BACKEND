from database import students_collection, vendors_collection, transactions_collection
from pymongo import MongoClient
from config import MONGODB_URL, DATABASE_NAME

def clear_collections():
    students_collection.delete_many({})
    vendors_collection.delete_many({})
    transactions_collection.delete_many({})

def seed_data():
    # Clear existing data
    clear_collections()

    # Add dummy students
    students = [
        {
            "student_id": "STU001",
            "name": "John Doe",
            "balance": 1000.0,
            "parent_id": "PAR001",
            "parent_phone": "+918600194737",
            "parent_name": "Mr. Doe",
            "class": "10th",
            "section": "A"
        },
        {
            "student_id": "STU002",
            "name": "Jane Smith",
            "balance": 1500.0,
            "parent_id": "PAR002",
            "parent_phone": "+918600194737",
            "parent_name": "Mr. Smith",
            "class": "9th",
            "section": "B"
        }
    ]
    students_collection.insert_many(students)

    # Add dummy vendors
    vendors = [
        {
            "vendor_id": "VEN001",
            "name": "Cafeteria Store",
            "upi_id": "cafeteria@upi",
            "store_type": "Food",
            "balance": 0.0
        },
        {
            "vendor_id": "VEN002",
            "name": "Stationary Shop",
            "upi_id": "stationary@upi",
            "store_type": "Stationary",
            "balance": 0.0
        }
    ]
    vendors_collection.insert_many(vendors)

    print("Dummy data has been added successfully!")

if __name__ == "__main__":
    seed_data() 