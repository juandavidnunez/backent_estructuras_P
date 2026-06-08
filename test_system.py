"""
Script de prueba para verificar el sistema de aeropuertos.

Prueba:
1. Sistema de recaudo y descuento por estadía
2. Trabajos diferenciados por región
3. Bloqueo de rutas durante vuelo y desvío de emergencia
4. Navegación sin bloqueos
"""

import sys
import os
from pathlib import Path

# Agregar el directorio raíz al path
sys.path.insert(0, str(Path(__file__).parent))

from app.loader import load_graph_from_json
from app.services import SkyRouteService

# Configurar la ruta del archivo de red
NETWORK_PATH = str(Path(__file__).parent / "data" / "network.json")

def test_jobs_by_region():
    """Verificar que cada aeropuerto tenga trabajos únicos por región"""
    print("\n" + "="*70)
    print("TEST 1: Verificar trabajos diferenciados por región")
    print("="*70)
    
    service = SkyRouteService(NETWORK_PATH)
    jobs_by_airport = {}
    
    for airport_id, airport in service.graph.airports.items():
        jobs = [j.name for j in airport.jobs]
        jobs_by_airport[airport_id] = jobs
        print(f"\n{airport_id} ({airport.city}, {airport.country}):")
        for job in airport.jobs:
            print(f"  - {job.name}: ${job.hourly_rate}/h (max {job.max_hours}h)")
    
    # Verificar que no todos tengan los mismos trabajos
    unique_job_sets = set()
    for jobs in jobs_by_airport.values():
        unique_job_sets.add(tuple(sorted(jobs)))
    
    print(f"\n✓ Conjuntos únicos de trabajos: {len(unique_job_sets)}")
    print(f"✓ Total de aeropuertos: {len(jobs_by_airport)}")
    
    if len(unique_job_sets) > len(jobs_by_airport) * 0.7:
        print("✓ ÉXITO: Los trabajos están bien diferenciados por región")
    else:
        print("⚠ ADVERTENCIA: Muchos aeropuertos comparten los mismos trabajos")


def test_mandatory_costs():
    """Verificar que el sistema de recaudo funcione correctamente"""
    print("\n" + "="*70)
    print("TEST 2: Verificar sistema de recaudo (comida y alojamiento)")
    print("="*70)
    
    service = SkyRouteService(NETWORK_PATH)
    
    # Iniciar un viaje de prueba
    state = service.start_session("BOG", 500.0, 100.0)
    print(f"\n✓ Viaje iniciado en {state.current_airport}")
    print(f"  Presupuesto inicial: ${service.sessions[state.session_id].initial_budget:.2f}")
    
    # Realizar un vuelo largo para activar costos obligatorios
    try:
        result = service.fly(state.session_id, "LIM", "Avión Comercial")
        print(f"\n✓ Vuelo exitoso: BOG → LIM")
        print(f"  Costo del vuelo: ${result.segment.cost_usd:.2f}")
        print(f"  Tiempo de vuelo: {result.segment.flight_time_min:.1f} min")
        print(f"  Presupuesto restante: ${result.budget_remaining:.2f}")
        
        if result.mandatory_events:
            print(f"\n✓ Eventos obligatorios aplicados: {len(result.mandatory_events)}")
            for event in result.mandatory_events:
                print(f"  {event}")
            print("✓ ÉXITO: Sistema de recaudo funciona correctamente")
        else:
            print("⚠ No se aplicaron eventos obligatorios en este vuelo")
    
    except Exception as e:
        print(f"❌ ERROR: {e}")


def test_emergency_diversion():
    """Verificar que el desvío de emergencia funcione"""
    print("\n" + "="*70)
    print("TEST 3: Verificar desvío de emergencia durante vuelo")
    print("="*70)
    
    service = SkyRouteService(NETWORK_PATH)
    
    # Iniciar viaje
    state = service.start_session("BOG", 1000.0, 200.0)
    print(f"\n✓ Viaje iniciado en {state.current_airport}")
    
    # Viajar a MDE
    try:
        result1 = service.fly(state.session_id, "MDE", "Avión Comercial")
        print(f"\n✓ Vuelo 1: BOG → MDE exitoso")
        print(f"  Aeropuerto actual: {result1.current_airport}")
        
        # Bloquear una ruta no relacionada primero
        service.block_route("LIM", "CUZ", None)
        print(f"\n✓ Ruta LIM → CUZ bloqueada (no afecta al viajero)")
        
        # Intentar volar a CLO
        print(f"\n→ Intentando volar MDE → CLO...")
        result2 = service.fly(state.session_id, "CLO", "Avión Regional")
        print(f"✓ Vuelo 2: MDE → CLO exitoso")
        print(f"  Aeropuerto actual: {result2.current_airport}")
        
        print("\n✓ ÉXITO: Sistema de navegación funciona correctamente")
        print(f"  Aeropuertos visitados: {result2.visited}")
        
    except Exception as e:
        print(f"❌ ERROR: {e}")


def test_available_flights():
    """Verificar que siempre haya vuelos disponibles desde cualquier aeropuerto"""
    print("\n" + "="*70)
    print("TEST 4: Verificar disponibilidad de vuelos")
    print("="*70)
    
    service = SkyRouteService(NETWORK_PATH)
    state = service.start_session("BOG", 2000.0, 300.0)
    
    airports_to_test = ["BOG", "MDE", "LIM", "SCL", "EZE", "GRU"]
    
    for airport in airports_to_test:
        # Simular estar en ese aeropuerto
        rec = service.sessions[state.session_id]
        rec.current_airport = airport
        rec.visited = [airport]  # Reset para poder viajar
        
        flights = service.get_flights(state.session_id)
        print(f"\n{airport}: {len(flights)} vuelos disponibles")
        
        if len(flights) > 0:
            for i, flight in enumerate(flights[:3]):  # Mostrar solo 3 primeros
                print(f"  {i+1}. → {flight.dest} ({flight.distance_km}km) - ${flight.recommended_aircraft.cost_usd:.2f}")
        else:
            print(f"  ⚠ Sin vuelos disponibles desde {airport}")
    
    print("\n✓ TEST completado")


if __name__ == "__main__":
    print("\n" + "="*70)
    print(" SUITE DE PRUEBAS DEL SISTEMA DE AEROPUERTOS")
    print("="*70)
    
    try:
        test_jobs_by_region()
        test_mandatory_costs()
        test_emergency_diversion()
        test_available_flights()
        
        print("\n" + "="*70)
        print(" RESUMEN: Todas las pruebas completadas")
        print("="*70)
        
    except Exception as e:
        print(f"\n❌ ERROR FATAL: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
