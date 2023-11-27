import os, torch
from PIL import Image
from vlmeval import *


class mPLUG_Owl2:

    def __init__(self, model_path='MAGAer13/mplug-owl2-llama2-7b', max_new_tokens=10, temperature=0.7): 
        from mplug_owl2.constants import IMAGE_TOKEN_INDEX, DEFAULT_IMAGE_TOKEN
        from mplug_owl2.conversation import conv_templates, SeparatorStyle
        from mplug_owl2.model.builder import load_pretrained_model
        from mplug_owl2.mm_utils import process_images, tokenizer_image_token, get_model_name_from_path, KeywordsStoppingCriteria
        model_name = get_model_name_from_path(model_path)
        tokenizer, model, image_processor, context_len = load_pretrained_model(model_path, None, model_name, load_8bit=False, load_4bit=False, device="cpu")

        self.model = model.cuda()
        self.device = self.model.device
        self.image_processor = image_processor
        tokenizer.padding_side = 'left'
        tokenizer.pad_token_id = tokenizer.eos_token_id
        self.tokenizer = tokenizer
        self.context_len = context_len
        self.max_new_tokens = max_new_tokens
        self.temperature = temperature

    def build_mmbench_prompt(self, img_dir, line):
        os.makedirs(img_dir, exist_ok=True)
        prompt_tmpl = "USER: <|image|>{}\n{}\n{}\nAnswer with the option’s letter from the given choices directly. ASSISTANT:"
        idx = line['index']
        img = line['image']
        tgt_path = osp.join(img_dir, f'{idx}.jpg')
        decode_base64_to_image_file(img, tgt_path)

        question = line['question']
        option_candidate = ['A', 'B', 'C', 'D', 'E']
        options = {
            cand: line[cand]
            for cand in option_candidate
            if cand in line and not pd.isna(line[cand])
        }
        options_prompt = ''
        for key, item in options.items():
            options_prompt += f'{key}. {item}\n'
        
        hint = line['hint'] if ('hint' in line and not pd.isna(line['hint'])) else 'N/A'
        prompt = prompt_tmpl.format(hint, question, options_prompt)
        return {'image': tgt_path, 'text': prompt}
    
    def generate(self, image_path, prompt):
        conv = conv_templates["mplug_owl2"].copy()
        roles = conv.roles

        image = Image.open(image_path).convert('RGB')
        max_edge = max(image.size) # We recommand you to resize to squared image for BEST performance.
        image = image.resize((max_edge, max_edge))

        image_tensor = process_images([image], self.image_processor)
        image_tensor = image_tensor.to(self.device, dtype=torch.float16)

        inp = DEFAULT_IMAGE_TOKEN + prompt
        conv.append_message(conv.roles[0], inp)
        conv.append_message(conv.roles[1], None)
        prompt = conv.get_prompt()

        input_ids = tokenizer_image_token(prompt, self.tokenizer, IMAGE_TOKEN_INDEX, return_tensors='pt').unsqueeze(0).to(self.device)
        stop_str = conv.sep2
        keywords = [stop_str]
        stopping_criteria = KeywordsStoppingCriteria(keywords, self.tokenizer, input_ids)
        with torch.inference_mode():
            output_ids = self.model.generate(
                input_ids,
                images=image_tensor,
                do_sample=True,
                temperature=self.temperature,
                max_new_tokens=self.max_new_tokens,
                use_cache=True,
                stopping_criteria=[stopping_criteria])

        outputs = self.tokenizer.decode(output_ids[0, input_ids.shape[1]:]).strip()
        return outputs.split('</s>')[0]

    def mmbench_generate(self, image_path, prompt):
        image = Image.open(image_path).convert('RGB')
        max_edge = max(image.size) # We recommand you to resize to squared image for BEST performance.
        image = image.resize((max_edge, max_edge))

        image_tensor = process_images([image], self.image_processor)
        image_tensor = image_tensor.to(self.device, dtype=torch.float16)

        input_ids = tokenizer_image_token(prompt, self.tokenizer, IMAGE_TOKEN_INDEX, return_tensors='pt').unsqueeze(0).to(self.device)
        with torch.inference_mode():
            output_ids = self.model.generate(
                input_ids=input_ids, 
                images=image_tensor, 
                do_sample=False, 
                num_beams=1, 
                max_new_tokens=self.max_new_tokens, 
                min_new_tokens=1, 
                length_penalty=1, 
                num_return_sequences=1, 
                output_hidden_states=True, 
                use_cache=True)
        answer = self.tokenizer.decode(output_ids[0, input_ids.shape[1]: ]).strip()
        return answer.split('</s>')[0]