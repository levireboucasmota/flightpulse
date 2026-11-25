import sys
import pandas as pd
import numpy as np
import requests

print("=" * 45) 
print("FLIGHTPULSE - ENVIRONMENT CHECK")
print("=" * 45)

print(f"Python: {sys.version}")
print(f"Pandas: {pd.__version__}")
print(f"NumPy: {np.__version__}")
print(f"Requests: {requests.__version__}")

print("\nEnvironment successfully initialized!")
