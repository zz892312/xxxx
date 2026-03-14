"""
External Web API Integration Demo - Milestone 3
BabyTrack+ Application

This script demonstrates integration with the USDA FoodData Central API
to fetch nutritional information for baby foods logged in feeding activities.

API: USDA FoodData Central
Documentation: https://fdc.nal.usda.gov/api-guide.html
Free tier available with API key registration
"""

import urllib.request
import urllib.parse
import json
import ssl

# USDA FoodData Central API Configuration
API_KEY = 'fidqTvsD9v3qeGJo1YzblRrqzBZR9AH6RQlN7Cjd'
BASE_URL = 'https://api.nal.usda.gov/fdc/v1'

ssl_context = ssl.create_default_context()


def search_food(query):
    """
    Search for food items in USDA FoodData Central database
    
    Args:
        query (str): Search term (e.g., "banana", "apple", "milk")
    
    Returns:
        dict: Search results from API
    """
    # Build URL with correct endpoint
    url = f"{BASE_URL}/foods/search"
    
    # Build query parameters
    params = {
        'query': query,
        'pageSize': 5,
        'api_key': API_KEY
    }
    
    query_string = urllib.parse.urlencode(params)
    full_url = f"{url}?{query_string}"
    
    print(f"\n→ Requesting: {url}?query={query}&pageSize=5&api_key=***")
    print(f"→ Search query: {query}\n")
    
    try:
        req = urllib.request.Request(full_url, headers={'User-Agent': 'BabyTrack+ Demo/1.0'})
        with urllib.request.urlopen(req, context=ssl_context, timeout=15) as response:
            data = response.read()
            return json.loads(data)
    except urllib.error.HTTPError as e:
        print(f"HTTP Error {e.code}: {e.reason}")
        try:
            error_body = e.read().decode()
            if len(error_body) < 500:
                print(f"Response: {error_body}")
        except:
            pass
        raise
    except urllib.error.URLError as e:
        print(f"URL Error: {e.reason}")
        raise
    except Exception as e:
        print(f"Error: {str(e)}")
        raise


def get_food_details(fdc_id):
    """
    Get detailed information about a specific food item
    
    Args:
        fdc_id (int): FDC ID of the food item
    
    Returns:
        dict: Food details from API
    """
    url = f"{BASE_URL}/food/{fdc_id}?api_key={API_KEY}"
    
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'BabyTrack+ Demo/1.0'})
        with urllib.request.urlopen(req, context=ssl_context, timeout=15) as response:
            data = response.read()
            return json.loads(data)
    except urllib.error.HTTPError as e:
        print(f"HTTP Error: {e.code}")
        raise
    except Exception as e:
        print(f"Error: {str(e)}")
        raise


def display_nutrition(food_item):
    """Display nutritional information in a readable format"""
    print('\n╔════════════════════════════════════════════════════════════╗')
    print('║                   NUTRITIONAL INFORMATION                  ║')
    print('╚════════════════════════════════════════════════════════════╝\n')
    
    print(f"Food: {food_item.get('description', 'N/A')}")
    print(f"Brand: {food_item.get('brandOwner', 'N/A')}")
    print(f"Category: {food_item.get('foodCategory', 'N/A')}")
    
    if 'foodNutrients' in food_item and food_item['foodNutrients']:
        print('\nKey Nutrients (per 100g):')
        print('─────────────────────────────────────────────────────────\n')
        
        # Display important nutrients for baby food
        important_nutrients = ['Energy', 'Protein', 'Carbohydrate', 'Sugars', 
                               'Fiber', 'Fat', 'Calcium', 'Iron', 'Vitamin C']
        
        for nutrient in food_item['foodNutrients']:
            nutrient_name = nutrient.get('nutrient', {}).get('name', nutrient.get('nutrientName', ''))
            if any(key in nutrient_name for key in important_nutrients):
                value = nutrient.get('amount', nutrient.get('value', 0))
                unit = nutrient.get('nutrient', {}).get('unitName', nutrient.get('unitName', ''))
                print(f"  • {nutrient_name}: {value} {unit}")


def demonstrate_web_api():
    """Main demonstration function"""
    print('\n╔════════════════════════════════════════════════════════════╗')
    print('║   BabyTrack+ - External Web API Demo                      ║')
    print('║   USDA FoodData Central API Integration                    ║')
    print('╚════════════════════════════════════════════════════════════╝\n')

    try:
        # Example 1: Search for baby-friendly foods
        print('========================================')
        print('1. Searching for Baby Foods: "banana"')
        print('========================================')
        
        search_results = search_food('banana')
        
        total_hits = search_results.get('totalHits', 0)
        foods = search_results.get('foods', [])
        
        print(f"✓ Found {total_hits} results")
        print(f"✓ Displaying top {len(foods)} items:\n")
        
        for index, food in enumerate(foods, 1):
            print(f"{index}. {food.get('description', 'N/A')}")
            print(f"   FDC ID: {food.get('fdcId', 'N/A')}")
            print(f"   Brand: {food.get('brandOwner', 'Generic')}")
            print()

        # Example 2: Get detailed nutrition for first result
        if foods:
            first_food = foods[0]
            
            print('\n========================================')
            print('2. Fetching Detailed Nutrition Information')
            print('========================================')
            
            food_details = get_food_details(first_food['fdcId'])
            display_nutrition(food_details)

        # Example 3: Search for another common baby food
        print('\n========================================')
        print('3. Searching for Baby Foods: "apple sauce"')
        print('========================================')
        
        apple_results = search_food('apple sauce')
        apple_foods = apple_results.get('foods', [])
        
        print(f"✓ Found {apple_results.get('totalHits', 0)} results")
        print(f"✓ Displaying top {min(3, len(apple_foods))} items:\n")
        
        for index, food in enumerate(apple_foods[:3], 1):
            print(f"{index}. {food.get('description', 'N/A')}")
            print(f"   Category: {food.get('foodCategory', 'N/A')}")
            print()

        print('\n╔════════════════════════════════════════════════════════════╗')
        print('║   ✓ External Web API Integration Successful!               ║')
        print('╚════════════════════════════════════════════════════════════╝\n')

        print('Use Cases in BabyTrack+:')
        print('  • Track nutritional content of solid foods fed to baby')
        print('  • Calculate daily calorie and nutrient intake')
        print('  • Generate feeding reports with nutrition data')
        print('  • Alert caregivers about potential allergens')
        print('  • Support informed feeding decisions with data\n')

    except Exception as error:
        print('\n✗ Error accessing USDA FoodData Central API:')
        print(f"  {str(error)}\n")
        print('Note: Ensure you have a valid API key and internet connection.')
        print('Register for free API key at: https://fdc.nal.usda.gov/api-key-signup.html\n')


if __name__ == '__main__':
    demonstrate_web_api()
