import torch
from peft import LoraConfig
from transformers import AutoProcessor, BitsAndBytesConfig, Idefics2ForConditionalGeneration, Qwen2VLModel, Qwen2VLConfig, AutoTokenizer, Qwen2VLForConditionalGeneration
from qwen_vl_utils import process_vision_info
from model.model import Model
from model.utils import setup_cache_dir

def get_model_tokenizer_processor(quantization_mode):
    model_name = "Qwen/Qwen2-VL-2B-Instruct"

    if quantization_mode == 8:
        quantization_config = BitsAndBytesConfig(load_in_8bit=True)
    elif quantization_mode == 4:
        quantization_config = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_compute_dtype=torch.float16,
            bnb_4bit_use_double_quant=True,
            bnb_4bit_quant_type="nf4"
        )
    else:
        # load the default model 
        quantization_config = None

    tokenizer = AutoTokenizer.from_pretrained(
        model_name,
        trust_remote_code=True
    )

    config = Qwen2VLConfig.from_pretrained(
        model_name,
        trust_remote_code=True
    )

    cache_dir = setup_cache_dir()

    if quantization_config is not None:
        model = Qwen2VLForConditionalGeneration.from_pretrained(
            model_name,
            config=config,
            quantization_config=quantization_config,
            device_map="auto",
            trust_remote_code=True,
            cache_dir=cache_dir
        )
    else:
        model = Qwen2VLForConditionalGeneration.from_pretrained(
            model_name,
            config=config,
            device_map="auto",
            trust_remote_code=True,
            cache_dir=cache_dir
        )

    processor = AutoProcessor.from_pretrained("Qwen/Qwen2-VL-2B-Instruct")


    return model, tokenizer, processor

class Qwen2VL(Model):
    def __init__(self, quantization_mode):
        self.model, self.tokenizer, self.processor = get_model_tokenizer_processor(quantization_mode)

    def process(self, texts, images):
        inputs = self.processor(text=texts, images=images, return_tensors="pt", padding=True)
        outputs = self.model(**inputs)
        return outputs
    
    def get_model_name(self):
        return "qwen2"

    def generate(self, texts, images):
        inputs = self.processor(text=texts, images=images, return_tensors="pt", padding=True)
        generated_ids = self.model.generate(**inputs, max_new_tokens=64)
        generated_texts = self.processor.batch_decode(generated_ids[:, inputs["input_ids"].size(1):], skip_special_tokens=True)
        return generated_texts

    def process_image_queries(self, images, queries):
        messages = []

        for idx, q in enumerate(queries):
            message = [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Answer briefly."},
                        {"type": "image", "image": images[idx][0], "resized_height": 280,"resized_width": 420},
                        {"type": "text", "text": q["en"]}
                    ]
                }
            ]
            
            messages.append(message)
        
        return self.process_generate(messages)


    def process_generate(self, messages):
        self.model.eval()
        
        torch.cuda.empty_cache()
        

        texts = [
            self.processor.apply_chat_template(msg, tokenize=False, add_generation_prompt=True)
            for msg in messages
        ]

        image_inputs, video_inputs = process_vision_info(messages)
        inputs = self.processor(
            text=texts,
            images=image_inputs,
            videos=video_inputs,
            padding=True,
            return_tensors="pt",
        )

        inputs = inputs.to("cuda")
        generated_ids = self.model.generate(**inputs, max_new_tokens=128)
        generated_ids_trimmed = [
            out_ids[len(in_ids) :] for in_ids, out_ids in zip(inputs.input_ids, generated_ids)
        ]
        output_texts = self.processor.batch_decode(
            generated_ids_trimmed, skip_special_tokens=True, clean_up_tokenization_spaces=False
        )
        return output_texts

    def get_processor(self):
        return self.processor