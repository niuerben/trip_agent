// 类型定义

export interface Location {
  longitude: number
  latitude: number
}

export interface Attraction {
  name: string
  address: string
  location: Location
  visit_duration: number
  description: string
  category?: string
  rating?: number
  photos?: string[]
  poi_id?: string
  image_url?: string
  ticket_price?: number
}

export interface Meal {
  type: 'breakfast' | 'lunch' | 'dinner' | 'snack'
  name: string
  address?: string
  location?: Location
  description?: string
  estimated_cost?: number
  poi_id?: string
}

export interface Hotel {
  name: string
  address: string
  location?: Location
  price_range: string
  rating: string
  distance: string
  type: string
  estimated_cost?: number
  poi_id?: string
}

export interface Budget {
  total_attractions: number
  total_hotels: number
  total_meals: number
  total_transportation: number
  total: number
}

export interface DayPlan {
  date: string
  day_index: number
  description: string
  transportation: string
  accommodation: string
  hotel?: Hotel
  attractions: Attraction[]
  meals: Meal[]
}

export interface WeatherInfo {
  date: string
  day_weather: string
  night_weather: string
  day_temp: number
  night_temp: number
  wind_direction: string
  wind_power: string
  source?: string
}

export interface TripPlan {
  city: string
  start_date: string
  end_date: string
  days: DayPlan[]
  weather_info: WeatherInfo[]
  overall_suggestions: string
  budget?: Budget
}

export interface ChangeSelector {
  name?: string
  semantic?: string
  day_index?: number
}

export interface ChangeTarget {
  name?: string
  semantic?: string
}

export interface ChangeOperation {
  operation: 'add_attraction' | 'delete_attraction' | 'replace_attraction' | 'update_day' | 'full_replan'
  selector?: ChangeSelector
  target?: ChangeTarget
  fields?: Record<string, unknown>
}

export interface ChangeSet {
  operations: ChangeOperation[]
}

export interface TripFormData {
  city: string
  start_date: string
  end_date: string
  travel_days: number
  transportation: string
  accommodation: string
  preferences: string[]
  free_text_input: string
  conversation_id?: string
  preference?: Preference
  current_plan?: TripPlan
  change_request?: string
  change_set?: ChangeSet
}

export type TripFormState = Omit<TripFormData, 'start_date' | 'end_date'> & {
  start_date: import('dayjs').Dayjs | null
  end_date: import('dayjs').Dayjs | null
}

export interface TripPlanResponse {
  success: boolean
  message: string
  data?: TripPlan
}

export interface Preference {
  prompt: string
}

export interface TalkMessage {
  role: 'user' | 'assistant'
  content: string
}

export interface ChatMessage {
  id: number
  conversation_id: string
  role: 'user' | 'assistant'
  content: string
  created_at: string
}

export interface TalkRequest {
  conversation_id?: string
  city?: string
  plan_context?: string
  messages?: TalkMessage[]
  message: string
}

export interface TalkResponse {
  success: boolean
  reply: string
  intent: 'chat' | 'replan'
  change_request?: string
  change_set?: ChangeSet
  top_suggestions: string[]
  preference?: Preference
  done: boolean
  messages: ChatMessage[]
}

export interface TalkSuggestionsRequest {
  conversation_id: string
  city?: string
  plan_context?: string
}

export interface TalkSuggestionsResponse {
  success: boolean
  top_suggestions: string[]
}

export interface ChatHistoryResponse {
  success: boolean
  messages: ChatMessage[]
}

