import pandas as pd
import numpy as np
import xgboost as xgb
from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report, precision_recall_curve
import joblib
from datetime import datetime, timedelta

def generar_dataset_y_entrenar():
    print("[1/5] Generando dataset sintético basado en telemetría de Bomba de Inyección...")
    np.random.seed(42)
    num_records = 5000
    
    # 1. Variables base (Operación Normal basada en tu JSON)
    timestamps = [datetime(2026, 1, 1) + timedelta(hours=i) for i in range(num_records)]
    temp_c = np.random.normal(loc=70.0, scale=5.0, size=num_records) # Asumimos 1000C era un pico/error de sensor
    vib_mm_s = np.random.normal(loc=2.1, scale=0.2, size=num_records)
    flp_psi = np.random.normal(loc=95.0, scale=3.0, size=num_records)
    thp_psi = np.random.normal(loc=450.0, scale=10.0, size=num_records)
    motor_amps = np.random.normal(loc=48.2, scale=1.5, size=num_records)
    flow_rate = np.random.normal(loc=1250.0, scale=20.0, size=num_records)
    water_cut = np.random.normal(loc=8.5, scale=0.5, size=num_records)
    
    y_target = np.zeros(num_records, dtype=int)
    
    # 2. Inyección de Fallas Reales (Degradación mecánica/eléctrica)
    # 48 horas antes de la falla, las variables empeoran drásticamente
    fallas_reales = [1200, 2800, 4200]
    for fp in fallas_reales:
        inicio = fp - 48
        y_target[inicio:fp] = 1 # 1 = Falla inminente en < 48h
        
        # Comportamiento físico de la falla: sube amperaje, sube vibración, cae caudal
        temp_c[inicio:fp] += np.linspace(0, 40, 48)       # Calentamiento
        vib_mm_s[inicio:fp] += np.linspace(0, 5.5, 48)    # Desbalanceo
        motor_amps[inicio:fp] += np.linspace(0, 15.0, 48) # Sobreesfuerzo
        flow_rate[inicio:fp] -= np.linspace(0, 300, 48)   # Pérdida de eficiencia
        thp_psi[inicio:fp] += np.linspace(0, 80, 48)      # Presión en cabezal sube por restricción

    # 3. Simulación de Correcciones Humanas (Falsos Positivos)
    # Momentos donde la métrica saltó (ej. arranque en frío, prueba de pozo) pero NO era falla.
    # El experto en Heimdall RCM registró un AICorrection indicando "Operación Normal".
    falsos_positivos = [2000, 3500]
    for fp in falsos_positivos:
        inicio = fp - 12 # Evento transitorio de 12 horas
        # Simulamos el pico
        vib_mm_s[inicio:fp] += np.random.uniform(3.0, 6.0, 12) 
        motor_amps[inicio:fp] += np.random.uniform(10.0, 20.0, 12)
        # CRÍTICO: La etiqueta se mantiene en 0 porque el humano lo corrigió. 
        # Esto enseña al modelo a no asustarse con picos cortos sin caída de caudal.
        y_target[inicio:fp] = 0 

    # 4. Construcción del DataFrame aplanado
    df = pd.DataFrame({
        "recorded_at": timestamps,
        "temperature_celsius": temp_c,
        "vibration_mm_s": vib_mm_s,
        "flpPsi": flp_psi,
        "thpPsi": thp_psi,
        "motorAmps": motor_amps,
        "flowRateBpd": flow_rate,
        "waterCutPercent": water_cut,
        "target_falla_48h": y_target
    })
    
    df.to_csv("dataset_bombas_inyeccion.csv", index=False)
    print(f"[+] Dataset 'dataset_bombas_inyeccion.csv' generado con {num_records} filas.")

    print("\n[2/5] Calculando variables temporales (Rolling Features)...")
    # El ML necesita entender la historia reciente, no solo el segundo actual
    ventanas = ["temperature_celsius", "vibration_mm_s", "motorAmps", "flowRateBpd"]
    for col in ventanas:
        df[f"{col}_media_12h"] = df[col].rolling(window=12, min_periods=1).mean()
        df[f"{col}_std_12h"] = df[col].rolling(window=12, min_periods=1).std().fillna(0)
        df[f"{col}_delta"] = df[col].diff().fillna(0) # Tasa de cambio brusco

    print("[3/5] Preparando datos para entrenamiento...")
    columnas_excluidas = ["recorded_at", "target_falla_48h"]
    features = [col for col in df.columns if col not in columnas_excluidas]
    
    X = df[features]
    y = df["target_falla_48h"]
    
    # Partición respetando la línea de tiempo
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, shuffle=False)
    
    # Manejo del desbalance (muchas más horas normales que horas de falla)
    peso_clase = (y_train == 0).sum() / max((y_train == 1).sum(), 1)
    
    print("[4/5] Entrenando modelo XGBoost...")
    modelo = xgb.XGBClassifier(
        n_estimators=150,
        max_depth=5,
        learning_rate=0.05,
        scale_pos_weight=peso_clase,
        eval_metric="logloss",
        random_state=42
    )
    
    modelo.fit(X_train, y_train)
    
    print("\n[5/5] Evaluación del Modelo:")
    predicciones = modelo.predict(X_test)
    print(classification_report(y_test, predicciones))
    
    joblib.dump(modelo, "modelo_bomba_inyeccion.pkl")
    joblib.dump(features, "columnas_modelo.pkl")
    print("\n[+] Archivos 'modelo_bomba_inyeccion.pkl' y 'columnas_modelo.pkl' listos para Producción.")

if __name__ == "__main__":
    generar_dataset_y_entrenar()